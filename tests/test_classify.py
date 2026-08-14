"""阶段一 classify 单测。"""

from pathlib import Path

import pytest

from src.pipeline import classify


@pytest.fixture()
def cfg():
    return {}


class TestExtRouting:
    def test_xlsx(self, tmp_path, cfg):
        f = tmp_path / "a.xlsx"
        f.touch()
        assert classify.run({"file": str(f)}, cfg).kind == "excel"

    def test_xls(self, tmp_path, cfg):
        f = tmp_path / "a.xls"
        f.touch()
        assert classify.run({"file": str(f)}, cfg).kind == "excel"

    @pytest.mark.parametrize("name", ["a.txt", "a.md", "a.eml", "A.TXT"])
    def test_text(self, tmp_path, cfg, name):
        f = tmp_path / name
        f.touch()
        assert classify.run({"file": str(f)}, cfg).kind == "text"

    @pytest.mark.parametrize("name", ["a.jpg", "a.jpeg", "a.png", "A.PNG"])
    def test_image(self, tmp_path, cfg, name):
        f = tmp_path / name
        f.touch()
        assert classify.run({"file": str(f)}, cfg).kind == "image"

    def test_unsupported(self, tmp_path, cfg):
        f = tmp_path / "a.docx"
        f.touch()
        r = classify.run({"file": str(f)}, cfg)
        assert r.kind == "unsupported"
        assert ".docx" in r.detail


class TestPdfSecondaryCheck:
    """PDF 二次判定：首页字符数 > 100 → pdf_digital（monkeypatch 掉真实 PDF 读取）。"""

    def test_digital(self, tmp_path, cfg, monkeypatch):
        f = tmp_path / "a.pdf"
        f.touch()
        monkeypatch.setattr(classify, "pdf_char_count", lambda p: 500)
        assert classify.run({"file": str(f)}, cfg).kind == "pdf_digital"

    def test_scanned(self, tmp_path, cfg, monkeypatch):
        f = tmp_path / "a.pdf"
        f.touch()
        monkeypatch.setattr(classify, "pdf_char_count", lambda p: 30)
        assert classify.run({"file": str(f)}, cfg).kind == "pdf_scanned"

    def test_boundary(self, tmp_path, cfg, monkeypatch):
        f = tmp_path / "a.pdf"
        f.touch()
        monkeypatch.setattr(classify, "pdf_char_count", lambda p: 100)
        # 恰好 100 不超过阈值 → 扫描件
        assert classify.run({"file": str(f)}, cfg).kind == "pdf_scanned"
