"""数据模型（设计方案 §4）。

约定：
- LLM 输出层只产出 *_raw 原文与 confidence / source_snippet；
- quantity / unit_price / lead_time_days / 归一化 unit 由规则阶段（V2/V5/V6）计算填入；
- flags 记录触发的规则号（V1~V7、H1），导出阶段据 confidence + flags 标黄。
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class QuoteLine(BaseModel):
    item_name: str = ""                      # 物料名称（必填，空则 V1 标黄）
    spec: str = ""                           # 规格型号
    quantity_raw: str = ""                   # 数量原文
    quantity: Optional[float] = None         # 解析后数量（V2）
    unit: str = ""                           # 单位（V6 归一化）
    unit_price_raw: str = ""                 # 单价原文（必填，空则 V1 标黄）
    unit_price: Optional[float] = None       # 解析后单价（V2）
    amount_raw: str = ""                     # 金额原文（如有）
    currency: str = "CNY"
    tax_included: Optional[bool] = None      # 含税与否（原文明确才有值）
    lead_time_raw: str = ""                  # 交期原文
    lead_time_days: Optional[int] = None     # 解析后交期天数（V5，M5）
    payment_terms: str = ""                  # 付款方式
    remark: str = ""
    confidence: Literal["high", "low"] = "high"
    source_snippet: str = ""                 # 原文片段（H1 溯源校验对象）
    flags: list[str] = Field(default_factory=list)  # 触发的规则号，如 ["V3", "H1"]


class SupplierQuote(BaseModel):
    source_file: str
    kind: str
    supplier_name: str = "未知供应商"        # 识别不到则 "未知供应商"
    lines: list[QuoteLine] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    """校验发现：(对象定位, 规则号, 说明)。"""

    target: str                              # 如 "华东机电.xlsx#行3"
    rule: str                                # V1~V7 / H1
    message: str


class ClassifyResult(BaseModel):
    file: str
    kind: Literal["excel", "pdf_digital", "pdf_scanned", "text", "image", "unsupported"]
    detail: str = ""


class RawContent(BaseModel):
    source_file: str
    kind: str
    raw_text: str = ""
    extraction_warnings: list[str] = Field(default_factory=list)
    low_ocr_lines: list[str] = Field(default_factory=list)  # OCR 低置信行（设计方案 §3.2）


# ---------- 阶段五：比价分析（M3） ----------


class GroupEntry(BaseModel):
    """某供应商对某物料组的一次报价（同供应商多文件已在合并阶段去重）。"""

    supplier_name: str
    source_file: str
    line: QuoteLine


class ItemGroup(BaseModel):
    """同一物料的多家报价集合 + 统计。"""

    key: str                                     # 归一化对齐 key
    item_name: str = ""                          # 展示用名称（取代表行）
    spec: str = ""                               # 展示用规格
    entries: list[GroupEntry] = Field(default_factory=list)
    review: bool = False                         # 低置信匹配：不合并、相邻放置、标黄待人工
    notes: list[str] = Field(default_factory=list)
    avg_price: Optional[float] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    deviations: dict[str, float] = Field(default_factory=dict)  # supplier -> 偏离均价
    min_lead_days: Optional[int] = None
    max_lead_days: Optional[int] = None
    median_lead_days: Optional[float] = None


class Comparison(BaseModel):
    suppliers: list[str] = Field(default_factory=list)
    groups: list[ItemGroup] = Field(default_factory=list)
    missing: list[dict] = Field(default_factory=list)   # {"item": ..., "supplier": ...} 缺报
    notes: list[str] = Field(default_factory=list)
