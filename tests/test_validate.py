"""阶段四 validate 单测：V1 / V2 / V6 逐条独立，不依赖网络与 LLM。"""

import pytest

from src.models import QuoteLine, SupplierQuote
from src.pipeline import validate
from src.pipeline.validate import parse_number


def _cfg():
    return {"units_file": "config/units.yml"}


def _quote(**line_over):
    base = dict(item_name="内六角螺钉", unit_price_raw="0.05", quantity_raw="5000", unit="个")
    base.update(line_over)
    return SupplierQuote(source_file="t.xlsx", kind="excel", lines=[QuoteLine(**base)])


class TestV1:
    def test_missing_price(self):
        q, findings = validate.run(_quote(unit_price_raw=""), _cfg())
        assert any(f.rule == "V1" and "单价" in f.message for f in findings)
        assert "V1" in q.lines[0].flags

    def test_missing_name(self):
        q, findings = validate.run(_quote(item_name="  "), _cfg())
        assert any(f.rule == "V1" and "物料名称" in f.message for f in findings)

    def test_ok(self):
        q, findings = validate.run(_quote(), _cfg())
        assert not [f for f in findings if f.rule == "V1"]


class TestParseNumber:
    @pytest.mark.parametrize("text,expected", [
        ("4件", 4.0),
        ("¥1,200.00", 1200.0),
        ("¥1,200.00（含税13%）", 1200.0),
        ("0.048元一个", 0.048),
        ("8块2一个", 8.2),
        ("25块一个", 25.0),
        ("68块钱一个", 68.0),
        ("1,250", 1250.0),
        ("-5", -5.0),
    ])
    def test_ok(self, text, expected):
        assert parse_number(text) == pytest.approx(expected)

    @pytest.mark.parametrize("text", ["", "面议", "价格详谈", None])
    def test_fail(self, text):
        assert parse_number(text or "") is None


class TestV2:
    def test_fill_parsed_values(self):
        q, _ = validate.run(_quote(quantity_raw="4件", unit_price_raw="¥1,200.00（含税13%）"), _cfg())
        assert q.lines[0].quantity == 4.0
        assert q.lines[0].unit_price == 1200.0

    def test_unparseable_flagged_keeps_raw(self):
        q, findings = validate.run(_quote(unit_price_raw="面议"), _cfg())
        line = q.lines[0]
        assert line.unit_price is None
        assert line.unit_price_raw == "面议"
        assert "V2" in line.flags
        assert any(f.rule == "V2" for f in findings)

    @pytest.mark.parametrize("raw", ["5O个", "l65元", "8.5O元", "1I件"])
    def test_ocr_confusion_flagged(self, raw):
        """数字与 O/I/l 相邻（OCR 混淆特征）：即使能解析出值也必须标黄。"""
        q, findings = validate.run(_quote(quantity_raw=raw), _cfg())
        assert "V2" in q.lines[0].flags
        assert any("混淆" in f.message for f in findings)


class TestV6:
    @pytest.mark.parametrize("raw,std", [
        ("个", "件"), ("pcs", "件"), ("PCS", "件"), ("件", "件"), ("台", "台"), ("set", "套"),
    ])
    def test_normalize(self, raw, std):
        q, _ = validate.run(_quote(unit=raw), _cfg())
        assert q.lines[0].unit == std

    def test_unknown_kept(self):
        q, _ = validate.run(_quote(unit="托"), _cfg())
        assert q.lines[0].unit == "托"


class TestV3:
    """金额核对：数量×单价 ≈ 金额（±2% 容差），不符标黄并注明差额。"""

    def _quote_amount(self, qty, price, amount):
        return _quote(quantity_raw=str(qty), unit_price_raw=str(price), amount_raw=amount)

    def test_match_passes(self):
        q, findings = validate.run(self._quote_amount(5000, 0.05, "250"), _cfg())
        assert not [f for f in findings if f.rule == "V3"]

    def test_within_tolerance_passes(self):
        q, findings = validate.run(self._quote_amount(3, 100, "305"), _cfg())  # +1.7%
        assert not [f for f in findings if f.rule == "V3"]

    def test_mismatch_flagged_with_diff(self):
        q, findings = validate.run(self._quote_amount(50, 8.5, "500"), _cfg())  # 425 ≠ 500
        v3 = [f for f in findings if f.rule == "V3"]
        assert v3 and "差额" in v3[0].message and "-75" in v3[0].message
        assert "V3" in q.lines[0].flags

    def test_amount_unparseable(self):
        q, findings = validate.run(self._quote_amount(50, 8.5, "总价面议"), _cfg())
        assert any(f.rule == "V3" and "无法解析" in f.message for f in findings)

    def test_no_amount_skips(self):
        q, findings = validate.run(_quote(), _cfg())
        assert not [f for f in findings if f.rule == "V3"]


class TestV4:
    def test_currency_detected(self):
        q, findings = validate.run(_quote(unit_price_raw="$100"), _cfg())
        assert q.lines[0].currency == "USD"
        assert any(f.rule == "V4" and "USD" in f.message for f in findings)

    def test_currency_hkd_before_usd(self):
        q, _ = validate.run(_quote(unit_price_raw="HK$50"), _cfg())
        assert q.lines[0].currency == "HKD"

    def test_default_cny_quiet(self):
        q, findings = validate.run(_quote(unit_price_raw="¥100"), _cfg())
        assert q.lines[0].currency == "CNY"
        assert not [f for f in findings if f.rule == "V4"]

    @pytest.mark.parametrize("remark,expected", [
        ("含税13%", True), ("未税", False), ("不含税", False), ("", None),
    ])
    def test_tax_filled_only_when_explicit(self, remark, expected):
        q, _ = validate.run(_quote(remark=remark), _cfg())
        assert q.lines[0].tax_included is expected


class TestParseLeadTime:
    @pytest.mark.parametrize("text,expected", [
        ("现货", 0), ("现货供应", 0), ("当天发货", 0),
        ("7天", 7), ("7 天", 7), ("3个工作日", 3), ("10天以内", 10),
        ("一周", 7), ("两周", 14), ("3周", 21), ("一个星期", 7),
        ("半个月", 15), ("一个月", 30), ("2个月", 60),
        ("7-10天", 10), ("7~10天", 10),
        ("订货要20天", 20), ("约15天左右", 15), ("货期12天", 12),
        ("二十天", 20), ("十二天", 12),
    ])
    def test_ok(self, text, expected):
        assert validate.parse_lead_time(text) == expected

    @pytest.mark.parametrize("text", ["", "尽快", "电议", None])
    def test_fail(self, text):
        assert validate.parse_lead_time(text or "") is None


class TestV5:
    def test_fill_days(self):
        q, _ = validate.run(_quote(lead_time_raw="两周"), _cfg())
        assert q.lines[0].lead_time_days == 14

    def test_unparseable_flagged(self):
        q, findings = validate.run(_quote(lead_time_raw="尽快"), _cfg())
        assert q.lines[0].lead_time_days is None
        assert "V5" in q.lines[0].flags
        assert any(f.rule == "V5" for f in findings)


class TestV7:
    def test_multiple_suppliers_flag_whole_file(self):
        q, findings = validate.run(
            _quote(), _cfg(),
            raw_text="华东机电设备有限公司报价单 ... 此价格由恒力工贸有限公司代理提供",
        )
        assert any(f.rule == "V7" for f in findings)
        assert "V7" in q.lines[0].flags
        assert any("V7" in w for w in q.warnings)

    def test_single_supplier_quiet(self):
        q, findings = validate.run(
            _quote(), _cfg(), raw_text="恒力工贸有限公司 报价单 ... 恒力工贸有限公司 业务部",
        )
        assert not [f for f in findings if f.rule == "V7"]

    def test_no_raw_text_skips(self):
        q, findings = validate.run(_quote(), _cfg())
        assert not [f for f in findings if f.rule == "V7"]
