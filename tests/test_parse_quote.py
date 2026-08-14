"""阶段三 parse_quote 单测：H1 溯源硬校验、供应商名优先级、降级、分块合并。"""

import json

import pytest

from src.llm.client import LLMClient
from src.models import RawContent
from src.pipeline import parse_quote

RAW_TEXT = "华东机电设备有限公司报价单\n| 1 | 内六角螺钉 | M8×20 | 件 | 5000 | 0.05 | 250 | 现货 |"


def _cfg(**llm_over):
    llm = {
        "base_url": "http://unused", "api_key_env": "UNUSED", "model": "m",
        "temperature": 0, "timeout": 1, "max_retries": 1, "retry_delay": 0,
        "structured_mode": "json_schema", "context_chars": 60000, "replay_dir": None,
    }
    llm.update(llm_over)
    return {
        "llm": llm,
        "prompts": {"parse_quote": "config/prompts/parse_quote.md"},
    }


def _line(**over):
    base = {
        "item_name": "内六角螺钉", "spec": "M8×20", "quantity_raw": "5000",
        "unit": "件", "unit_price_raw": "0.05", "amount_raw": "250",
        "currency": "CNY", "tax_included": None, "lead_time_raw": "现货",
        "payment_terms": "", "remark": "", "confidence": "high",
        "source_snippet": "| 1 | 内六角螺钉 | M8×20 | 件 | 5000 | 0.05 | 250 | 现货 |",
    }
    base.update(over)
    return base


def _transport_of(payload):
    def transport(messages, rf, cfg):
        return json.dumps(payload, ensure_ascii=False)
    return transport


def _run(payload, raw_text=RAW_TEXT, source_file="华东机电.xlsx", **llm_over):
    raw = RawContent(source_file=source_file, kind="excel", raw_text=raw_text)
    client = LLMClient(_cfg(**llm_over), transport=_transport_of(payload))
    return parse_quote.run(raw, _cfg(**llm_over), client)


class TestNormal:
    def test_parse_and_supplier_from_content(self):
        q = _run({"supplier_name": "华东机电设备有限公司", "lines": [_line()]})
        assert q.supplier_name == "华东机电设备有限公司"
        assert len(q.lines) == 1
        assert q.lines[0].confidence == "high"
        assert q.lines[0].flags == []

    def test_supplier_fallback_to_filename(self):
        q = _run({"supplier_name": "未知供应商", "lines": [_line()]})
        assert q.supplier_name == "华东机电"

    def test_empty_raw_text_skips_llm(self):
        raw = RawContent(source_file="a.txt", kind="text", raw_text="   ")
        client = LLMClient(_cfg(), transport=lambda *a: 1 / 0)
        q = parse_quote.run(raw, _cfg(), client)
        assert q.lines == []
        assert any("跳过" in w for w in q.warnings)


class TestH1:
    """验收标准：人为构造 LLM 返回含原文不存在片段的 mock 响应，对应行必须被强制标黄。"""

    def test_hallucinated_snippet_forced_low(self):
        q = _run({
            "supplier_name": "华东机电设备有限公司",
            "lines": [_line(source_snippet="这段原文里根本不存在")],
        })
        line = q.lines[0]
        assert line.confidence == "low"
        assert "H1" in line.flags
        assert any("H1" in w for w in q.warnings)

    def test_empty_snippet_forced_low(self):
        q = _run({"supplier_name": "x", "lines": [_line(source_snippet="")]})
        assert q.lines[0].confidence == "low"
        assert "H1" in q.lines[0].flags

    def test_whitespace_normalized(self):
        # snippet 与原文只差空白 → 归一化后应通过
        q = _run({
            "supplier_name": "x",
            "lines": [_line(source_snippet="内六角螺钉 M8×20 件 5000")],
        })
        assert q.lines[0].confidence == "high"
        assert q.lines[0].flags == []


class TestDegrade:
    def test_llm_failure_not_raise(self):
        def bad_transport(messages, rf, cfg):
            raise ConnectionError("服务不可用")

        raw = RawContent(source_file="a.txt", kind="text", raw_text=RAW_TEXT)
        client = LLMClient(_cfg(max_retries=2), transport=bad_transport)
        q = parse_quote.run(raw, _cfg(max_retries=2), client)
        assert q.lines == []
        assert any(w.startswith("LLM_FAILED") for w in q.warnings)


class TestOCRFlag:
    """low_ocr_lines 硬校验：报价行溯源片段落在低置信 OCR 行上 → 强制标黄。"""

    def test_line_on_low_confidence_ocr_row(self):
        payload = {"supplier_name": "x", "lines": [_line()]}
        raw = RawContent(
            source_file="s.pdf", kind="pdf_scanned", raw_text=RAW_TEXT,
            low_ocr_lines=["| 1 | 内六角螺钉 | M8×20 | 件 | 5000 | 0.05 | 250 | 现货 |"],
        )
        client = LLMClient(_cfg(), transport=_transport_of(payload))
        q = parse_quote.run(raw, _cfg(), client)
        assert q.lines[0].confidence == "low"
        assert "OCR" in q.lines[0].flags

    def test_unaffected_when_no_overlap(self):
        payload = {"supplier_name": "x", "lines": [_line()]}
        raw = RawContent(
            source_file="s.pdf", kind="pdf_scanned", raw_text=RAW_TEXT,
            low_ocr_lines=["完全不相干的另一行"],
        )
        client = LLMClient(_cfg(), transport=_transport_of(payload))
        q = parse_quote.run(raw, _cfg(), client)
        assert q.lines[0].confidence == "high"
        assert q.lines[0].flags == []


class TestChunking:
    def test_chunk_merge(self):
        # 把上下文阈值调到极小，强制切块；transport 按块内容分别应答
        def transport(messages, rf, cfg):
            # 只看"报价原文"区段（模板 few-shot 示例里也含有这些物料名）
            chunk = messages[1]["content"].split("# 报价原文")[-1]
            lines = []
            if "内六角螺钉" in chunk:
                lines.append(_line())
            if "6204 轴承" in chunk:
                lines.append(_line(item_name="深沟球轴承", source_snippet="6204 轴承 8.5元"))
            return json.dumps({
                "supplier_name": "华东机电" if "报价单" in chunk else "",
                "lines": lines,
            }, ensure_ascii=False)

        raw_text = RAW_TEXT + "\n6204 轴承 8.5元"
        raw = RawContent(source_file="a.txt", kind="text", raw_text=raw_text)
        cfg = _cfg(context_chars=60)  # 80% = 48 字符，必切块
        client = LLMClient(cfg, transport=transport)
        q = parse_quote.run(raw, cfg, client)
        assert len(q.lines) == 2
        assert q.supplier_name == "华东机电"
        assert any("切块" in w or "切为" in w for w in q.warnings)
