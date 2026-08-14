"""阶段三：LLM 结构化解析（核心环节，含 H1 溯源硬校验）。

要点（设计方案 §3.3）：
- JSON Schema 强制结构化输出；temperature=0；重试由 LLMClient 负责；
- 所有字段值必须逐字来自原文 —— LLM 只输出 *_raw 原文，计算留给规则阶段；
- H1 硬校验：source_snippet 归一化空白后必须是 raw_text 子串，否则强制
  confidence=low 并打 H1 标（代码实现，不靠 LLM 自觉）；
- LLM 连续重试失败：该文件降级（warnings 记 LLM_FAILED），不中断批处理；
- raw_text 超过上下文 80% 时按行切块分批提取后合并。
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import ValidationError

from src.llm.client import LLMClient, LLMError
from src.models import QuoteLine, RawContent, SupplierQuote

SCHEMA_NAME = "supplier_quote"

SYSTEM_PROMPT = "你是采购报价单结构化提取助手。你只输出 JSON，不输出任何其他文字。"

# LLM 输出层只含原文字段；quantity/unit_price/lead_time_days 等计算值禁止出现。
QUOTE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "supplier_name": {"type": "string"},
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_name": {"type": "string"},
                    "spec": {"type": "string"},
                    "quantity_raw": {"type": "string"},
                    "unit": {"type": "string"},
                    "unit_price_raw": {"type": "string"},
                    "amount_raw": {"type": "string"},
                    "currency": {"type": "string"},
                    "tax_included": {"type": ["boolean", "null"]},
                    "lead_time_raw": {"type": "string"},
                    "payment_terms": {"type": "string"},
                    "remark": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "low"]},
                    "source_snippet": {"type": "string"},
                },
                "required": [
                    "item_name", "spec", "quantity_raw", "unit", "unit_price_raw",
                    "amount_raw", "currency", "tax_included", "lead_time_raw",
                    "payment_terms", "remark", "confidence", "source_snippet",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["supplier_name", "lines"],
    "additionalProperties": False,
}


def run(input: RawContent | dict, config: dict, llm: LLMClient) -> SupplierQuote:
    raw = RawContent.model_validate(input)
    quote = SupplierQuote(source_file=raw.source_file, kind=raw.kind)
    quote.warnings.extend(raw.extraction_warnings)
    if not raw.raw_text.strip():
        quote.warnings.append("无可用文本，跳过 LLM 解析")
        return quote

    template = Path(config["prompts"]["parse_quote"]).read_text(encoding="utf-8")
    limit = int(config["llm"].get("context_chars", 60000) * 0.8)
    chunks = _chunk_text(raw.raw_text, limit)
    if len(chunks) > 1:
        quote.warnings.append(f"raw_text 超长，已切为 {len(chunks)} 块分批提取后合并")

    supplier_name = ""
    all_lines: list[QuoteLine] = []
    for chunk in chunks:
        user = template.replace("{{file_name}}", raw.source_file).replace(
            "{{raw_text}}", chunk
        )
        try:
            data = llm.complete_json(
                system=SYSTEM_PROMPT, user=user,
                schema_name=SCHEMA_NAME, schema=QUOTE_SCHEMA,
            )
        except LLMError as e:
            # 降级：原始文本由导出阶段原样写入单独 Sheet，整体标黄
            quote.warnings.append(f"LLM_FAILED: {e}")
            quote.lines = []
            return quote
        name = (data.get("supplier_name") or "").strip()
        if name and name != "未知供应商" and not supplier_name:
            supplier_name = name
        for line_data in data.get("lines") or []:
            try:
                all_lines.append(QuoteLine.model_validate(line_data))
            except ValidationError as e:
                quote.warnings.append(f"LLM 返回行无法通过模型校验，已丢弃: {e.errors()[:1]}")

    # 供应商名称识别优先级：文件内容 > 文件名 > "未知供应商"
    quote.supplier_name = supplier_name or Path(raw.source_file).stem or "未知供应商"

    # H1 溯源硬校验（代码实现，不靠 LLM 自觉）
    norm_raw = _normalize(raw.raw_text)
    for i, line in enumerate(all_lines):
        if not line.source_snippet or _normalize(line.source_snippet) not in norm_raw:
            line.confidence = "low"
            if "H1" not in line.flags:
                line.flags.append("H1")
            quote.warnings.append(
                f"H1 幻觉嫌疑: 第{i + 1}行 source_snippet 无法在原文中检索到"
            )

    # OCR 低置信行硬校验：报价行溯源片段落在低置信 OCR 行上 → 强制标黄
    norm_low = [_normalize(l) for l in raw.low_ocr_lines if _normalize(l)]
    if norm_low:
        for i, line in enumerate(all_lines):
            snip = _normalize(line.source_snippet)
            if snip and any(snip in nl or nl in snip for nl in norm_low):
                line.confidence = "low"
                if "OCR" not in line.flags:
                    line.flags.append("OCR")
                quote.warnings.append(f"OCR 低置信: 第{i + 1}行落在低置信 OCR 行上")
    quote.lines = all_lines
    return quote


def _normalize(s: str) -> str:
    """归一化：去除空白与 Markdown 表格管道符（提取阶段自产出的结构符号）。"""
    return re.sub(r"[\s|]+", "", s or "")


def _chunk_text(text: str, limit: int) -> list[str]:
    """按行切块（报价单极少超长，简单切块即可，不做语义切分）。"""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for line in text.splitlines(keepends=True):
        if size + len(line) > limit and buf:
            chunks.append("".join(buf))
            buf, size = [], 0
        buf.append(line)
        size += len(line)
    if buf:
        chunks.append("".join(buf))
    return chunks
