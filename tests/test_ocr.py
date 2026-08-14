"""OCR 管线单测：矫正容错、低置信行收集、引擎降级。OCR 引擎本体用 monkeypatch 替换。"""

import numpy as np
import pytest

from src.pipeline import ocr
from src.pipeline.extract_raw import run as extract_run
from src.models import ClassifyResult


def _cfg(engine="auto", threshold=0.85):
    return {"ocr": {"engine": engine, "dpi": 300, "min_char_confidence": threshold}}


class TestCollect:
    def test_low_confidence_split(self):
        lines, low = ocr._collect([("好行", 0.99), ("差行", 0.5), ("临界", 0.85)], _cfg())
        assert lines == ["好行", "差行", "临界"]
        assert low == ["差行"]  # 0.85 不低于阈值


class TestEngineSelection:
    def test_unavailable_raises(self, monkeypatch):
        monkeypatch.setitem(__import__("sys").modules, "paddleocr", None)
        monkeypatch.setitem(__import__("sys").modules, "rapidocr_onnxruntime", None)
        with pytest.raises(ocr.OCRUnavailable):
            ocr._select_engine(_cfg())

    def test_forced_engine_missing(self, monkeypatch):
        import sys
        monkeypatch.setitem(sys.modules, "paddleocr", None)
        with pytest.raises(ocr.OCRUnavailable, match="paddle"):
            ocr._select_engine(_cfg(engine="paddle"))


class TestCorrectImage:
    def test_deskew(self, tmp_path):
        """合成旋转文本图像 → 矫正后输出文件存在且尺寸合法。"""
        cv2 = pytest.importorskip("cv2")
        img = np.full((200, 400, 3), 255, np.uint8)
        cv2.putText(img, "QUOTE", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 3)
        m = cv2.getRotationMatrix2D((200, 100), 3.0, 1.0)
        rotated = cv2.warpAffine(img, m, (400, 200), borderValue=(255, 255, 255))
        src = tmp_path / "rot.png"
        dst = tmp_path / "fixed.png"
        cv2.imwrite(str(src), rotated)
        out = ocr.correct_image(src, dst)
        assert out == str(dst)
        assert dst.exists()

    def test_bad_input_falls_back(self, tmp_path):
        src = tmp_path / "not_an_image.png"
        src.write_bytes(b"not an image")
        assert ocr.correct_image(src, tmp_path / "out.png") == str(src)


class TestExtractIntegration:
    def test_engine_unavailable_degrades(self, tmp_path, monkeypatch):
        """无 OCR 引擎：警告 + 空文本，不抛异常。"""
        import sys
        monkeypatch.setitem(sys.modules, "paddleocr", None)
        monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)
        f = tmp_path / "a.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n")  # 假 png
        raw = extract_run(ClassifyResult(file=str(f), kind="image"), _cfg())
        assert raw.raw_text == ""
        assert any("OCR 引擎不可用" in w for w in raw.extraction_warnings)

    def test_ocr_failure_degrades(self, tmp_path, monkeypatch):
        f = tmp_path / "a.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n")

        def boom(*a, **k):
            raise RuntimeError("ocr crash")
        monkeypatch.setattr(ocr, "run_ocr_on_image", boom)
        raw = extract_run(ClassifyResult(file=str(f), kind="image"), _cfg())
        assert raw.raw_text == ""
        assert any("OCR 处理失败" in w for w in raw.extraction_warnings)

    def test_low_ocr_lines_propagated(self, tmp_path, monkeypatch):
        f = tmp_path / "a.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n")
        monkeypatch.setattr(
            ocr, "run_ocr_on_image",
            lambda p, c: (["正常行", "模糊行"], ["模糊行"]),
        )
        raw = extract_run(ClassifyResult(file=str(f), kind="image"), _cfg())
        assert raw.raw_text == "正常行\n模糊行"
        assert raw.low_ocr_lines == ["模糊行"]
        assert any("置信度" in w for w in raw.extraction_warnings)
