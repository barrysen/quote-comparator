"""OCR 管线（阶段二子模块）：图片 / 扫描 PDF → OpenCV 矫正 → 文字识别。

引擎选型（设计方案 §2.2 为 PaddleOCR）：本模块按 "paddle 优先、rapid 降级、
都没有则 OCRUnavailable 优雅降级" 实现，settings.yml 可用 ocr.engine 强制指定：
    auto    优先 PaddleOCR，未安装则用 rapidocr-onnxruntime（同一 PP-OCR 模型家族）
    paddle  仅 PaddleOCR
    rapid   仅 rapidocr-onnxruntime
注：开发环境 PaddlePaddle  wheel 下载受限时，rapidocr-onnxruntime 是等价轻量替代；
换回 PaddleOCR 只需安装 paddlepaddle + paddleocr，无需改代码。

输出统一为 (全部文本行, 低置信行)，行结构保留给 LLM 与 low_ocr_lines 硬校验。
"""

from __future__ import annotations

import tempfile
from pathlib import Path


class OCRUnavailable(Exception):
    """未安装任何可用 OCR 引擎。"""


_ENGINE_CACHE: dict[str, object] = {}


def _select_engine(config: dict) -> str:
    pref = (config.get("ocr") or {}).get("engine", "auto")
    if pref in ("auto", "paddle"):
        try:
            import paddle  # noqa: F401 —— paddleocr 半装状态下也要能发现
            import paddleocr  # noqa: F401
            return "paddle"
        except ImportError:
            if pref == "paddle":
                raise OCRUnavailable("ocr.engine=paddle 但未安装 paddleocr/paddlepaddle")
    if pref in ("auto", "rapid"):
        try:
            import onnxruntime  # noqa: F401 —— rapidocr 半装（缺 onnxruntime）视为不可用
            import rapidocr_onnxruntime  # noqa: F401
            return "rapid"
        except ImportError:
            if pref == "rapid":
                raise OCRUnavailable("ocr.engine=rapid 但未安装 rapidocr-onnxruntime/onnxruntime")
    raise OCRUnavailable("未安装 OCR 引擎（paddleocr 或 rapidocr-onnxruntime）")


def _ocr_image(image_path: str | Path, config: dict) -> list[tuple[str, float]]:
    """对单张图片做 OCR，返回 [(文本行, 置信度)]，按阅读顺序。"""
    engine = _select_engine(config)
    if engine == "paddle":
        if "paddle" not in _ENGINE_CACHE:
            from paddleocr import PaddleOCR

            _ENGINE_CACHE["paddle"] = PaddleOCR(use_angle_cls=False, lang="ch", show_log=False)
        result = _ENGINE_CACHE["paddle"].ocr(str(image_path))
        lines = []
        for page in result or []:
            for box in page or []:
                lines.append((str(box[1][0]), float(box[1][1])))
        return lines

    if "rapid" not in _ENGINE_CACHE:
        from rapidocr_onnxruntime import RapidOCR

        _ENGINE_CACHE["rapid"] = RapidOCR()
    result, _ = _ENGINE_CACHE["rapid"](str(image_path))
    return [(str(item[1]), float(item[2])) for item in result or []]


def correct_image(src: str | Path, dst: str | Path) -> str:
    """OpenCV 矫正拍照件：去歪斜 + 检测到清晰四边形轮廓时做透视矫正。

    任何一步失败都回退为原图（矫正是增强，不是必经路径）。
    """
    src, dst = str(src), str(dst)
    import cv2
    import numpy as np

    img = cv2.imread(src)
    if img is None:
        return src
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 去歪斜：文本像素最小外接矩形角度
        bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        coords = np.column_stack(np.where(bw > 0))
        if len(coords) > 0:
            angle = cv2.minAreaRect(coords)[-1]
            if angle > 45:
                angle -= 90
            if 0.3 < abs(angle) < 15:
                h, w = img.shape[:2]
                m = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
                img = cv2.warpAffine(
                    img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
                )
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 透视矫正：找占画面比例足够大的四边形（纸张/表格轮廓）
        h, w = gray.shape[:2]
        edged = cv2.Canny(gray, 50, 150)
        contours, _ = cv2.findContours(edged, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
            approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
            if len(approx) == 4 and cv2.contourArea(approx) > 0.3 * h * w:
                pts = approx.reshape(4, 2).astype("float32")
                ordered = _order_points(pts)
                w2 = int(max(np.linalg.norm(ordered[0] - ordered[1]),
                             np.linalg.norm(ordered[2] - ordered[3])))
                h2 = int(max(np.linalg.norm(ordered[0] - ordered[3]),
                             np.linalg.norm(ordered[1] - ordered[2])))
                target = np.array([[0, 0], [w2, 0], [w2, h2], [0, h2]], dtype="float32")
                m = cv2.getPerspectiveTransform(ordered, target)
                img = cv2.warpPerspective(img, m, (w2, h2))
                break
    except Exception:  # noqa: BLE001 —— 矫正失败回退原图
        return src
    cv2.imwrite(dst, img)
    return dst


def _order_points(pts):
    import numpy as np

    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).ravel()
    return np.array([
        pts[np.argmin(s)],    # 左上
        pts[np.argmin(diff)],  # 右上
        pts[np.argmax(s)],    # 右下
        pts[np.argmax(diff)],  # 左下
    ], dtype="float32")


def _collect(lines_with_score: list[tuple[str, float]], config: dict) -> tuple[list[str], list[str]]:
    threshold = float((config.get("ocr") or {}).get("min_char_confidence", 0.85))
    lines = [t for t, _ in lines_with_score]
    low = [t for t, s in lines_with_score if s < threshold]
    return lines, low


def run_ocr_on_image(image_path: str | Path, config: dict) -> tuple[list[str], list[str]]:
    """图片 → (全部行, 低置信行)。"""
    with tempfile.TemporaryDirectory(prefix="quote_ocr_") as tmp:
        corrected = correct_image(image_path, Path(tmp) / "corrected.png")
        return _collect(_ocr_image(corrected, config), config)


def run_ocr_on_pdf(pdf_path: str | Path, config: dict) -> tuple[list[str], list[str]]:
    """扫描 PDF → 300 DPI 转图 → 逐页矫正 + OCR → (全部行, 低置信行)。"""
    import pypdfium2 as pdfium

    dpi = int((config.get("ocr") or {}).get("dpi", 300))
    all_lines: list[tuple[str, float]] = []
    with tempfile.TemporaryDirectory(prefix="quote_ocr_") as tmp:
        pdf = pdfium.PdfDocument(str(pdf_path))
        try:
            for i in range(len(pdf)):
                page = pdf[i]
                img_path = Path(tmp) / f"page{i}.png"
                page.render(scale=dpi / 72).to_pil().save(img_path)
                corrected = correct_image(img_path, Path(tmp) / f"page{i}_corrected.png")
                all_lines.extend(_ocr_image(corrected, config))
        finally:
            pdf.close()
    return _collect(all_lines, config)
