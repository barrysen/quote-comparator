"""阶段五 compare 单测：规则对齐 / LLM 兜底 / 同供应商合并 / 统计 / 缺报。

全部手工构造 QuoteLine；LLM 判定用注入的 mock transport，不依赖网络。
"""

import json

import pytest

from src.llm.client import LLMClient
from src.models import QuoteLine, SupplierQuote
from src.pipeline import compare
from src.pipeline.compare import item_key, normalize_text


def _cfg(tmp_path=None):
    return {
        "llm": {
            "base_url": "http://unused", "api_key_env": "UNUSED", "model": "m",
            "temperature": 0, "timeout": 1, "max_retries": 1, "retry_delay": 0,
            "structured_mode": "json_schema", "context_chars": 60000, "replay_dir": None,
        },
        "prompts": {"match_items": "config/prompts/match_items.md"},
        "compare": {"price_deviation_threshold": 0.15, "lead_time_factor": 2.0},
    }


def _line(name, spec, price=None, lead=None, confidence="high", flags=None):
    return QuoteLine(
        item_name=name, spec=spec,
        unit_price_raw=str(price) if price is not None else "",
        unit_price=price, lead_time_days=lead,
        confidence=confidence, flags=flags or [],
    )


def _quote(supplier, source_file, lines):
    return SupplierQuote(
        source_file=source_file, kind="excel", supplier_name=supplier, lines=lines
    )


def _llm_of(payload):
    def transport(messages, rf, cfg):
        return json.dumps(payload, ensure_ascii=False)
    return LLMClient(_cfg(), transport=transport)


class TestNormalize:
    @pytest.mark.parametrize("a,b", [
        ("内六角螺钉 M8×20", "内六角螺钉 m8*20"),
        ("Ｍ８×２０", "m8x20"),          # 全角 → 半角
        ("SC63*100", "sc63×100"),
        (" 8M-720 ", "8m-720"),
    ])
    def test_variants_equal(self, a, b):
        assert normalize_text(a) == normalize_text(b)

    def test_key(self):
        assert item_key("内六角螺钉", "M8×20") == item_key("内六角螺钉", "M8*20")


class TestSupplierMerge:
    def test_supplement_overrides(self):
        main = _quote("供应商A", "供应商A.xlsx", [_line("轴承", "6204", 8.5)])
        supp = _quote("供应商A", "供应商A-补充.txt", [_line("轴承", "6204", 8.2)])
        items, suppliers, notes = compare.merge_suppliers([main, supp])
        assert suppliers == ["供应商A"]
        entry = items["供应商A"][item_key("轴承", "6204")]
        assert entry.source_file == "供应商A-补充.txt"
        assert entry.line.unit_price == 8.2
        assert any("覆盖" in n for n in notes)


class TestFirstPass:
    def test_exact_grouping_across_suppliers(self):
        qa = _quote("A", "a.xlsx", [_line("内六角螺钉", "M8×20", 0.05)])
        qb = _quote("B", "b.txt", [_line("内六角螺钉", "M8*20", 0.048)])
        cmp = compare.run({"quotes": [qa.model_dump(), qb.model_dump()]}, _cfg(), llm=None)
        assert len(cmp.groups) == 1
        assert {e.supplier_name for e in cmp.groups[0].entries} == {"A", "B"}

    def test_unmatched_stay_separate(self):
        qa = _quote("A", "a.xlsx", [_line("深沟球轴承", "6204", 8.5)])
        qb = _quote("B", "b.txt", [_line("6204轴承", "", 8.2)])
        cmp = compare.run({"quotes": [qa.model_dump(), qb.model_dump()]}, _cfg(), llm=None)
        assert len(cmp.groups) == 2  # 无 LLM 兜底时不合并

    def test_prefilter_cjk_overlap(self):
        """OCR 噪音导致规格不一致（62O4 vs 6204）时，中文名称子串仍能把候选对送进 LLM。"""
        assert compare._prefilter("深沟球轴承 62O4", "深沟球轴承 6204")
        assert not compare._prefilter("内六角螺钉 M8×20", "接近开关 M12 NPN")


class TestLLMFallback:
    def _quotes(self):
        qa = _quote("A", "a.xlsx", [_line("深沟球轴承", "6204", 8.5)])
        qb = _quote("B", "b.txt", [_line("6204轴承", "", 8.2)])
        return [qa.model_dump(), qb.model_dump()]

    def test_high_confidence_merged(self):
        llm = _llm_of({"results": [
            {"id": "0", "same": True, "confidence": "high", "reason": "规格一致"}
        ]})
        cmp = compare.run({"quotes": self._quotes()}, _cfg(), llm)
        assert len(cmp.groups) == 1
        assert {e.supplier_name for e in cmp.groups[0].entries} == {"A", "B"}
        assert any("合并" in n for n in cmp.notes)

    def test_low_confidence_not_merged_and_review(self):
        """保守策略：低置信一律不合并，相邻放置并标 review。"""
        llm = _llm_of({"results": [
            {"id": "0", "same": True, "confidence": "low", "reason": "不确定"}
        ]})
        cmp = compare.run({"quotes": self._quotes()}, _cfg(), llm)
        assert len(cmp.groups) == 2
        assert all(g.review for g in cmp.groups)
        keys = [g.key for g in cmp.groups]
        assert abs(keys.index(item_key("6204轴承", "")) - keys.index(item_key("深沟球轴承", "6204"))) == 1

    def test_not_same_untouched(self):
        llm = _llm_of({"results": [
            {"id": "0", "same": False, "confidence": "high", "reason": "不同物料"}
        ]})
        cmp = compare.run({"quotes": self._quotes()}, _cfg(), llm)
        assert len(cmp.groups) == 2
        assert not any(g.review for g in cmp.groups)

    def test_llm_failure_conservative(self):
        def bad(messages, rf, cfg):
            raise ConnectionError("down")
        llm = LLMClient(_cfg(), transport=bad)
        cmp = compare.run({"quotes": self._quotes()}, _cfg(), llm)
        assert len(cmp.groups) == 2
        assert any("失败" in n for n in cmp.notes)
        assert all(g.review for g in cmp.groups)


class TestStats:
    def test_price_stats_and_deviation(self):
        qa = _quote("A", "a.xlsx", [_line("电机", "1.5kW", 100.0)])
        qb = _quote("B", "b.xlsx", [_line("电机", "1.5kW", 140.0)])
        cmp = compare.run({"quotes": [qa.model_dump(), qb.model_dump()]}, _cfg(), llm=None)
        g = cmp.groups[0]
        assert g.min_price == 100.0
        assert g.max_price == 140.0
        assert g.avg_price == 120.0
        assert g.deviations["B"] == pytest.approx(1 / 6, rel=1e-3)

    def test_lead_stats(self):
        qa = _quote("A", "a.xlsx", [_line("气缸", "SC63", 100.0, lead=5)])
        qb = _quote("B", "b.xlsx", [_line("气缸", "SC63", 100.0, lead=20)])
        cmp = compare.run({"quotes": [qa.model_dump(), qb.model_dump()]}, _cfg(), llm=None)
        g = cmp.groups[0]
        assert g.min_lead_days == 5
        assert g.max_lead_days == 20


class TestMissing:
    def test_missing_detected_only_when_multi(self):
        qa = _quote("A", "a.xlsx", [_line("轴承", "6204", 8.5), _line("气缸", "SC63", 100.0)])
        qb = _quote("B", "b.xlsx", [_line("轴承", "6204", 8.2)])
        qc = _quote("C", "c.xlsx", [_line("轴承", "6204", 8.3)])
        cmp = compare.run(
            {"quotes": [q.model_dump() for q in (qa, qb, qc)]}, _cfg(), llm=None
        )
        # 轴承有 3 家 → 无缺报；气缸只 1 家 → 不构成缺报
        assert cmp.missing == []
        # 轴承 A/B/C 都报；若 C 未报轴承则记缺报
        qa2 = _quote("A", "a.xlsx", [_line("轴承", "6204", 8.5)])
        qb2 = _quote("B", "b.xlsx", [_line("轴承", "6204", 8.2)])
        qc2 = _quote("C", "c.xlsx", [_line("气缸", "SC63", 100.0)])
        cmp2 = compare.run(
            {"quotes": [q.model_dump() for q in (qa2, qb2, qc2)]}, _cfg(), llm=None
        )
        assert {"item": "轴承 6204", "supplier": "C"} in [
            {"item": m["item"], "supplier": m["supplier"]} for m in cmp2.missing
        ]
