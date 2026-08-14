"""阶段二 extract_raw 单测（excel / text 主线；M4 前 image 走降级警告）。"""

from pathlib import Path

import pytest

from src.models import ClassifyResult
from src.pipeline import extract_raw

FIXTURE_FILES = Path(__file__).parent / "fixtures" / "files"


@pytest.fixture()
def cfg():
    return {}


class TestExcel:
    def test_xlsx_to_markdown(self, cfg):
        c = ClassifyResult(file=str(FIXTURE_FILES / "华东机电.xlsx"), kind="excel")
        raw = extract_raw.run(c, cfg)
        assert raw.source_file == "华东机电.xlsx"
        assert "Sheet: 报价单" in raw.raw_text
        assert "| 序号 | 物料名称 |" in raw.raw_text
        assert "内六角螺钉" in raw.raw_text
        assert "M8×20" in raw.raw_text
        # 8 条物料行
        assert raw.raw_text.count("| 现货 |") >= 2
        assert not raw.extraction_warnings

    def test_cell_str_number(self):
        assert extract_raw._cell_str(250.0) == "250"
        assert extract_raw._cell_str(0.05) == "0.05"
        assert extract_raw._cell_str(None) == ""
        assert extract_raw._cell_str("a|b\nc") == "a｜b c"


class TestText:
    def test_read_utf8(self, cfg):
        c = ClassifyResult(file=str(FIXTURE_FILES / "铭泰五交化.txt"), kind="text")
        raw = extract_raw.run(c, cfg)
        assert "铭泰五交化" in raw.raw_text
        assert "8块2" in raw.raw_text
        assert not raw.extraction_warnings

    def test_read_gbk(self, tmp_path, cfg):
        f = tmp_path / "gbk.txt"
        f.write_bytes("报价：内六角螺钉 0.05 元/件".encode("gbk"))
        c = ClassifyResult(file=str(f), kind="text")
        raw = extract_raw.run(c, cfg)
        assert "内六角螺钉" in raw.raw_text

    def test_empty_file(self, tmp_path, cfg):
        f = tmp_path / "empty.txt"
        f.touch()
        c = ClassifyResult(file=str(f), kind="text")
        raw = extract_raw.run(c, cfg)
        assert raw.raw_text == ""
        assert "空文件" in raw.extraction_warnings


class TestDegraded:
    def test_image_ocr_degrades_gracefully(self, tmp_path, monkeypatch):
        """image 走 OCR 管线；无引擎或损坏文件 → 警告 + 空文本，不中断。"""
        import sys
        monkeypatch.setitem(sys.modules, "paddleocr", None)
        monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)
        f = tmp_path / "a.png"
        f.touch()
        c = ClassifyResult(file=str(f), kind="image")
        raw = extract_raw.run(c, cfg)
        assert raw.raw_text == ""
        assert raw.extraction_warnings

    def test_unsupported(self, cfg):
        c = ClassifyResult(file="a.docx", kind="unsupported", detail="不支持的格式: .docx")
        raw = extract_raw.run(c, cfg)
        assert raw.raw_text == ""
        assert raw.extraction_warnings


class TestPdfDigital:
    def test_hengli_pdf(self, cfg):
        """电子 PDF（reportlab 生成的样本）：文本 + 表格都要提取到。"""
        pdfplumber = pytest.importorskip("pdfplumber")
        c = ClassifyResult(file=str(FIXTURE_FILES / "恒力工贸.pdf"), kind="pdf_digital")
        raw = extract_raw.run(c, cfg)
        assert "恒力工贸有限公司" in raw.raw_text
        assert "内六角螺钉" in raw.raw_text
        assert "含税13%" in raw.raw_text and "未税" in raw.raw_text
        assert "|" in raw.raw_text  # 表格 Markdown 化
