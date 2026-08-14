"""阶段四：规则校验。

每条规则一个独立函数 check(quote, ctx) -> list[Finding]，全部可单测、不依赖 LLM。
V1 必填 / V2 数值解析 / V3 金额核对 / V4 币种税率 / V5 交期解析 / V6 单位归一 / V7 供应商一致性。

ctx 约定：{"config": dict, "units": dict, "raw_text": str | None}
（V7 需要原文扫描公司名，由 CLI 从阶段二产物传入；无 raw_text 时 V7 跳过。）
"""

from __future__ import annotations

import re

from src.config_loader import load_units
from src.models import Finding, SupplierQuote


def run(
    input: SupplierQuote | dict, config: dict, raw_text: str | None = None
) -> tuple[SupplierQuote, list[Finding]]:
    quote = SupplierQuote.model_validate(input)
    ctx = {
        "config": config,
        "units": load_units(config["units_file"]),
        "raw_text": raw_text,
    }
    findings: list[Finding] = []
    for check in RULES:
        findings.extend(check(quote, ctx))
    return quote, findings


def _loc(quote: SupplierQuote, index: int) -> str:
    return f"{quote.source_file}#行{index + 1}"


def _flag(line, rule: str) -> None:
    if rule not in line.flags:
        line.flags.append(rule)


# ---------- V1 必填 ----------

def check_v1_required(quote: SupplierQuote, ctx: dict) -> list[Finding]:
    """物料名称、单价为空 → 标黄。"""
    out: list[Finding] = []
    for i, line in enumerate(quote.lines):
        missing = []
        if not line.item_name.strip():
            missing.append("物料名称")
        if not line.unit_price_raw.strip():
            missing.append("单价")
        if missing:
            _flag(line, "V1")
            out.append(Finding(
                target=_loc(quote, i), rule="V1",
                message=f"必填字段缺失: {'、'.join(missing)}",
            ))
    return out


# ---------- V2 数值解析 ----------

_NUM_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
# 口语金额："8块2" → 8.2，"8块2毛5" → 8.25
_KUAI_RE = re.compile(r"(\d+)\s*块\s*(\d{1,2})(?!\d)")
# OCR 字符混淆：数字与 0/O、1/I/l 相邻（如 "5O个" "l65元"）→ 值可能错，必须标黄
_OCR_CONFUSE_RE = re.compile(r"[0-9][OIl]|[OIl][0-9]")


def parse_number(text: str) -> float | None:
    """把 '4件' / '¥1,200.00（含税13%）' / '8块2' 等原文解析为数值；失败返回 None。

    只取第一个数字（税率等附注在价格之后，不会被误取）。
    """
    if not text:
        return None
    m = _KUAI_RE.search(text)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = _NUM_RE.search(text.replace("，", ","))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def check_v2_numbers(quote: SupplierQuote, ctx: dict) -> list[Finding]:
    """数量 / 单价文本解析为数值；解析失败标黄，保留原文。

    数字与 O/I/l 相邻（OCR 0/O、1/I/l 混淆特征）时即使能解析出值也标黄——
    此时解析出的值可能是错的（"5O个" 会被解析成 5 而非 50）。
    """
    out: list[Finding] = []
    for i, line in enumerate(quote.lines):
        for attr_raw, attr_num, label in (
            ("quantity_raw", "quantity", "数量"),
            ("unit_price_raw", "unit_price", "单价"),
        ):
            raw = getattr(line, attr_raw).strip()
            if not raw:
                continue
            if _OCR_CONFUSE_RE.search(raw):
                _flag(line, "V2")
                out.append(Finding(
                    target=_loc(quote, i), rule="V2",
                    message=f"{label}疑似 OCR 字符混淆（0/O、1/I/l），解析值需人工核对: {raw!r}",
                ))
            value = parse_number(raw)
            if value is None:
                _flag(line, "V2")
                out.append(Finding(
                    target=_loc(quote, i), rule="V2",
                    message=f"{label}无法解析为数值（保留原文）: {raw!r}",
                ))
            else:
                setattr(line, attr_num, value)
    return out


# ---------- V6 单位归一 ----------

def check_v6_units(quote: SupplierQuote, ctx: dict) -> list[Finding]:
    """单位映射到标准表（个/件/pcs → 件）；映射表见 config/units.yml。"""
    units_map: dict[str, str] = ctx["units"]
    for line in quote.lines:
        u = line.unit.strip()
        if not u:
            continue
        std = units_map.get(u.lower())
        if std:
            line.unit = std
    return []  # 纯归一，不产生 Finding


# ---------- V3 金额核对 ----------

def check_v3_amount(quote: SupplierQuote, ctx: dict) -> list[Finding]:
    """原文同时有数量、单价、金额时：核对 数量×单价 ≈ 金额（±2% 容差）。

    报价笔误是真实痛点：不符标黄并注明差额。
    """
    tolerance = float(ctx["config"].get("compare", {}).get("amount_tolerance", 0.02))
    out: list[Finding] = []
    for i, line in enumerate(quote.lines):
        amount_raw = line.amount_raw.strip()
        if not amount_raw or line.quantity is None or line.unit_price is None:
            continue
        amount = parse_number(amount_raw)
        if amount is None:
            _flag(line, "V3")
            out.append(Finding(
                target=_loc(quote, i), rule="V3",
                message=f"金额无法解析为数值（保留原文）: {amount_raw!r}",
            ))
            continue
        calc = line.quantity * line.unit_price
        if amount == 0:
            mismatch = calc != 0
        else:
            mismatch = abs(calc - amount) > tolerance * abs(amount)
        if mismatch:
            _flag(line, "V3")
            out.append(Finding(
                target=_loc(quote, i), rule="V3",
                message=f"金额不符: {line.quantity:g}×{line.unit_price:g}={calc:g} ≠ 报价金额 {amount:g}（差额 {calc - amount:+g}）",
            ))
    return out


# ---------- V4 币种 / 税率 ----------

_CURRENCY_PATTERNS = [
    ("HKD", re.compile(r"HK\$|HKD|港币|港元", re.I)),
    ("USD", re.compile(r"\$|USD|美元|美金", re.I)),
    ("EUR", re.compile(r"€|EUR|欧元", re.I)),
]


def _detect_currency(text: str) -> str | None:
    for code, pattern in _CURRENCY_PATTERNS:
        if pattern.search(text):
            return code
    return None


def check_v4_currency_tax(quote: SupplierQuote, ctx: dict) -> list[Finding]:
    """识别币种（默认 CNY）与"含税/未税"字样，标注到字段，不做换算。"""
    out: list[Finding] = []
    for i, line in enumerate(quote.lines):
        text = " ".join([line.unit_price_raw, line.amount_raw, line.remark])
        detected = _detect_currency(text)
        if detected and line.currency != detected:
            out.append(Finding(
                target=_loc(quote, i), rule="V4",
                message=f"原文币种疑似 {detected}，与标记 {line.currency} 不一致（已改为 {detected}，未做换算）",
            ))
            line.currency = detected
        if line.tax_included is None:
            tax_text = f"{line.remark} {line.unit_price_raw} {line.source_snippet}"
            if re.search(r"不含税|未税", tax_text):
                line.tax_included = False
            elif "含税" in tax_text:
                line.tax_included = True
    return out


# ---------- V5 交期解析 ----------

_CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
           "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_to_int(s: str) -> int | None:
    """中文数字（≤99）：'七'→7，'十'→10，'十二'→12，'二十'→20。"""
    if s.isdigit():
        return int(s)
    if "十" in s:
        left, _, right = s.partition("十")
        tens = _CN_NUM.get(left, 1) if left else 1
        ones = _CN_NUM.get(right, 0) if right else 0
        if left and left not in _CN_NUM or right and right not in _CN_NUM:
            return None
        return tens * 10 + ones
    if len(s) == 1 and s in _CN_NUM:
        return _CN_NUM[s]
    return None


def parse_lead_time(text: str) -> int | None:
    """交期文本 → 天数。'现货'→0，'7天'→7，'两周'→14，'半个月'→15，'一个月'→30；
    区间取大值（'7-10天'→10）；解析失败返回 None。"""
    if not text:
        return None
    t = text.strip()
    if re.search(r"现货|当天|即日|即刻", t):
        return 0
    t = re.sub(r"约|左右|大概|大约|订货|货期|交期|内|需|要", "", t)
    num = r"(\d+|[一二两三四五六七八九十]+)"
    m = re.search(num + r"\s*[-~到至]\s*" + num + r"\s*(?:个)?(?:工作日|天|日)", t)
    if m:
        vals = [_cn_to_int(m.group(1)), _cn_to_int(m.group(2))]
        return max(v for v in vals if v is not None) if any(v is not None for v in vals) else None
    m = re.search(num + r"\s*(?:个)?(?:工作日|天|日)", t)
    if m:
        return _cn_to_int(m.group(1))
    m = re.search(num + r"\s*(?:个)?(?:星期|周)", t)
    if m:
        n = _cn_to_int(m.group(1))
        return n * 7 if n is not None else None
    if re.search(r"半(?:个)?月", t):
        return 15
    m = re.search(num + r"\s*(?:个)?月", t)
    if m:
        n = _cn_to_int(m.group(1))
        return n * 30 if n is not None else None
    return None


def check_v5_lead_time(quote: SupplierQuote, ctx: dict) -> list[Finding]:
    """交期文本解析为天数字段；解析失败保留原文并标黄。"""
    out: list[Finding] = []
    for i, line in enumerate(quote.lines):
        raw = line.lead_time_raw.strip()
        if not raw:
            continue
        days = parse_lead_time(raw)
        if days is None:
            _flag(line, "V5")
            out.append(Finding(
                target=_loc(quote, i), rule="V5",
                message=f"交期无法解析为天数（保留原文）: {raw!r}",
            ))
        else:
            line.lead_time_days = days
    return out


# ---------- V7 供应商一致性 ----------

_COMPANY_RE = re.compile(r"[\u4e00-\u9fff]{2,15}?(?:有限公司|公司|工厂|商行|贸易部|销售部)")


def check_v7_supplier_consistency(quote: SupplierQuote, ctx: dict) -> list[Finding]:
    """同一文件原文中出现多个不同供应商名称 → 标黄整个文件。"""
    raw_text = ctx.get("raw_text") or ""
    if not raw_text:
        return []
    names = {m.group(0) for m in _COMPANY_RE.finditer(raw_text)}
    # 互相包含的视为同一家（"华东机电有限公司" vs "华东机电设备…有限公司" 场景防御）
    distinct = {
        n for n in names if not any(n != m and (n in m or m in n) for m in names)
    }
    if len(distinct) <= 1:
        return []
    for line in quote.lines:
        _flag(line, "V7")
    quote.warnings.append(f"V7 供应商一致性: 文中出现多个供应商名称 {sorted(distinct)}")
    return [Finding(
        target=quote.source_file, rule="V7",
        message=f"同一文件出现多个供应商名称: {'、'.join(sorted(distinct))}，整个文件标黄待人工确认",
    )]


RULES = (
    check_v1_required,
    check_v2_numbers,
    check_v3_amount,
    check_v4_currency_tax,
    check_v5_lead_time,
    check_v6_units,
    check_v7_supplier_consistency,
)
