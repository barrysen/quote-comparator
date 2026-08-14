"""阶段一：格式分拣。

输入：{"file": 路径}
输出：ClassifyResult{file, kind: excel|pdf_digital|pdf_scanned|text|image|unsupported}

PDF 二次判定：首页可提取字符数 > 100 → pdf_digital，否则 pdf_scanned。
"""

from __future__ import annotations

from pathlib import Path

from src.models import ClassifyResult

EXCEL_EXTS = {".xlsx", ".xls"}
TEXT_EXTS = {".txt", ".md", ".eml"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
PDF_CHAR_THRESHOLD = 100


def run(input: dict, config: dict) -> ClassifyResult:
    path = Path(input["file"])
    ext = path.suffix.lower()
    if ext in EXCEL_EXTS:
        return ClassifyResult(file=str(path), kind="excel")
    if ext in TEXT_EXTS:
        return ClassifyResult(file=str(path), kind="text")
    if ext in IMAGE_EXTS:
        return ClassifyResult(file=str(path), kind="image")
    if ext == ".pdf":
        chars = pdf_char_count(path)
        kind = "pdf_digital" if chars > PDF_CHAR_THRESHOLD else "pdf_scanned"
        return ClassifyResult(
            file=str(path), kind=kind, detail=f"首页可提取字符数={chars}"
        )
    return ClassifyResult(
        file=str(path), kind="unsupported", detail=f"不支持的格式: {ext or '(无扩展名)'}"
    )


def pdf_char_count(path: Path) -> int:
    """pdfplumber 读取首页可提取字符数；打不开按 0 处理（交给扫描/OCR 管线）。"""
    import pdfplumber  # 延迟导入：仅 PDF 判定需要

    try:
        with pdfplumber.open(str(path)) as pdf:
            if not pdf.pages:
                return 0
            return len(pdf.pages[0].extract_text() or "")
    except Exception:  # noqa: BLE001 —— 损坏 PDF 不中断批处理
        return 0
