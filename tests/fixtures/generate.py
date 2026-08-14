"""虚拟样本集生成脚本（设计方案 §9）—— 没有真实数据时的开发燃料。

虚拟询价项目："XX 产线备件采购"，5 家虚拟供应商、同一批 8 种物料。
M2 生成 3 份 Excel/文本样本（含刻意埋入的脏数据）；M4 补充 PDF/图片样本。

用法:
    python tests/fixtures/generate.py

产物:
    tests/fixtures/files/          样本文件（工具的输入）
    tests/fixtures/expected/       每份样本的期望提取结果（关键字段）
    tests/fixtures/ground_truth.json  LLM 输出级完整真值（make_replay.py 用）
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).parent
FILES_DIR = FIXTURES / "files"
EXPECTED_DIR = FIXTURES / "expected"

# 同一批 8 种物料（名称, 规格型号, 标准单位, 询价数量）
ITEMS = [
    ("内六角螺钉", "M8×20", "件", 5000),
    ("深沟球轴承", "6204", "个", 50),
    ("球阀", "304不锈钢 DN15", "个", 10),
    ("工业吸尘器滤芯", "适配XX-2000", "个", 4),
    ("三相异步电机", "1.5kW", "台", 2),
    ("聚氨酯同步带", "8M-720", "条", 10),
    ("气缸", "SC63×100", "个", 4),
    ("接近开关", "M12 NPN 常开", "个", 20),
]

# 华东机电（基准）单价 / 交期；轴承金额故意写错（50×8.5=425 → 500），供 V3 校验
HUADONG_PRICE = [0.05, 8.5, 46, 65, 1280, 39, 168, 26]
HUADONG_LEAD = ["现货", "7天", "15天", "10天", "20天", "7天", "12天", "现货"]
HUADONG_AMOUNT_DIRTY = {"深沟球轴承": 500}  # 应为 425


def _fmt_num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


# ---------------------------------------------------------------- 华东机电.xlsx

def gen_huadong_xlsx() -> tuple[list[dict], list[dict]]:
    """规范表格基准样本。返回 (ground_truth_lines, expected_lines)。"""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "报价单"
    ws.append(["华东机电设备有限公司报价单"])
    ws.append(["报价日期：2026-08-10", "", "", "付款方式：月结30天"])
    ws.append([])
    ws.append(["序号", "物料名称", "规格型号", "单位", "数量", "单价(元)", "金额(元)", "交期", "备注"])
    gt_lines, exp_lines = [], []
    for i, (name, spec, unit, qty) in enumerate(ITEMS, start=1):
        price = HUADONG_PRICE[i - 1]
        amount = HUADONG_AMOUNT_DIRTY.get(name, round(qty * price, 2))
        lead = HUADONG_LEAD[i - 1]
        ws.append([i, name, spec, unit, qty, price, amount, lead, ""])
        gt_lines.append({
            "item_name": name, "spec": spec,
            "quantity_raw": str(qty), "unit": unit,
            "unit_price_raw": _fmt_num(price), "amount_raw": _fmt_num(amount),
            "currency": "CNY", "tax_included": None,
            "lead_time_raw": lead, "payment_terms": "", "remark": "",
            "confidence": "high",
            "snippet_hint": name,
        })
        exp_lines.append({
            "item_name": name, "spec_contains": spec.split()[0],
            "quantity": qty, "unit_price": price,
        })
    wb.save(FILES_DIR / "华东机电.xlsx")
    return gt_lines, exp_lines


# ---------------------------------------------------------------- 铭泰五交化.txt
# 微信消息风格：无表格散文、"两周"式模糊交期、单位"个/pcs"混用、口语价格"8块2"

MINGTAI_TEXT = """刘工，报价来了，你看下：
内六角螺钉M8*20的，0.048元一个，5000个240块，现货
6204轴承8块2一个，一周发货
304不锈钢球阀DN15的，45一个含税，货期两周
吸尘器滤芯XX-2000的68块钱一个，订货要20天
1.5千瓦电机1250一台，有现货
同步带8M-720的38一条，现货
气缸SC63*100的165一个，10天
接近开关M12 NPN的25块一个，现货，按pcs算也行
以上都不含运费，款到发货。铭泰五交化 老王
"""

MINGTAI_GT = [
    {"item_name": "内六角螺钉", "spec": "M8*20", "quantity_raw": "5000个", "unit": "个",
     "unit_price_raw": "0.048元一个", "amount_raw": "240块", "currency": "CNY",
     "tax_included": None, "lead_time_raw": "现货", "payment_terms": "款到发货",
     "remark": "", "confidence": "high", "snippet_hint": "内六角"},
    {"item_name": "6204轴承", "spec": "", "quantity_raw": "", "unit": "个",
     "unit_price_raw": "8块2一个", "amount_raw": "", "currency": "CNY",
     "tax_included": None, "lead_time_raw": "一周", "payment_terms": "款到发货",
     "remark": "", "confidence": "high", "snippet_hint": "6204"},
    {"item_name": "304不锈钢球阀", "spec": "DN15", "quantity_raw": "", "unit": "个",
     "unit_price_raw": "45一个", "amount_raw": "", "currency": "CNY",
     "tax_included": True, "lead_time_raw": "两周", "payment_terms": "款到发货",
     "remark": "", "confidence": "high", "snippet_hint": "球阀"},
    {"item_name": "吸尘器滤芯", "spec": "XX-2000", "quantity_raw": "", "unit": "个",
     "unit_price_raw": "68块钱一个", "amount_raw": "", "currency": "CNY",
     "tax_included": None, "lead_time_raw": "20天", "payment_terms": "款到发货",
     "remark": "", "confidence": "high", "snippet_hint": "吸尘器"},
    {"item_name": "电机", "spec": "1.5千瓦", "quantity_raw": "", "unit": "台",
     "unit_price_raw": "1250一台", "amount_raw": "", "currency": "CNY",
     "tax_included": None, "lead_time_raw": "现货", "payment_terms": "款到发货",
     "remark": "", "confidence": "high", "snippet_hint": "电机"},
    {"item_name": "同步带", "spec": "8M-720", "quantity_raw": "", "unit": "条",
     "unit_price_raw": "38一条", "amount_raw": "", "currency": "CNY",
     "tax_included": None, "lead_time_raw": "现货", "payment_terms": "款到发货",
     "remark": "", "confidence": "high", "snippet_hint": "同步带"},
    {"item_name": "气缸", "spec": "SC63*100", "quantity_raw": "", "unit": "个",
     "unit_price_raw": "165一个", "amount_raw": "", "currency": "CNY",
     "tax_included": None, "lead_time_raw": "10天", "payment_terms": "款到发货",
     "remark": "", "confidence": "high", "snippet_hint": "气缸"},
    {"item_name": "接近开关", "spec": "M12 NPN", "quantity_raw": "", "unit": "个",
     "unit_price_raw": "25块一个", "amount_raw": "", "currency": "CNY",
     "tax_included": None, "lead_time_raw": "现货", "payment_terms": "款到发货",
     "remark": "按pcs算也行", "confidence": "high", "snippet_hint": "接近开关"},
]

MINGTAI_EXPECTED = [
    {"item_name": "内六角螺钉", "spec_contains": "M8", "quantity": 5000, "unit_price": 0.048},
    {"item_name": "6204轴承", "spec_contains": "", "quantity": None, "unit_price": 8.2},
    {"item_name": "304不锈钢球阀", "spec_contains": "DN15", "quantity": None, "unit_price": 45},
    {"item_name": "吸尘器滤芯", "spec_contains": "XX-2000", "quantity": None, "unit_price": 68},
    {"item_name": "电机", "spec_contains": "1.5", "quantity": None, "unit_price": 1250},
    {"item_name": "同步带", "spec_contains": "8M-720", "quantity": None, "unit_price": 38},
    {"item_name": "气缸", "spec_contains": "SC63", "quantity": None, "unit_price": 165},
    {"item_name": "接近开关", "spec_contains": "M12", "quantity": None, "unit_price": 25},
]


def gen_mingtai_txt():
    (FILES_DIR / "铭泰五交化.txt").write_text(MINGTAI_TEXT, encoding="utf-8")
    return MINGTAI_GT, MINGTAI_EXPECTED


# ---------------------------------------------------------------- 华东机电-补充.txt
# 同一供应商第二次报价（M3 验证同供应商多文件合并）

BUCHONG_TEXT = """华东机电设备有限公司 补充报价

1、工业吸尘器滤芯 适配XX-2000型，单价62元/个，数量4个，交期10天
2、接近开关 M12 NPN 常开，单价25.5元/个，数量20个，现货

以上与主报价单不一致之处，以本补充报价为准。
2026年8月12日
"""

BUCHONG_GT = [
    {"item_name": "工业吸尘器滤芯", "spec": "适配XX-2000型", "quantity_raw": "4个", "unit": "个",
     "unit_price_raw": "62元/个", "amount_raw": "", "currency": "CNY",
     "tax_included": None, "lead_time_raw": "10天", "payment_terms": "",
     "remark": "", "confidence": "high", "snippet_hint": "吸尘器"},
    {"item_name": "接近开关", "spec": "M12 NPN 常开", "quantity_raw": "20个", "unit": "个",
     "unit_price_raw": "25.5元/个", "amount_raw": "", "currency": "CNY",
     "tax_included": None, "lead_time_raw": "现货", "payment_terms": "",
     "remark": "", "confidence": "high", "snippet_hint": "接近开关"},
]

BUCHONG_EXPECTED = [
    {"item_name": "工业吸尘器滤芯", "spec_contains": "XX-2000", "quantity": 4, "unit_price": 62},
    {"item_name": "接近开关", "spec_contains": "M12", "quantity": 20, "unit_price": 25.5},
]


def gen_buchong_txt():
    (FILES_DIR / "华东机电-补充.txt").write_text(BUCHONG_TEXT, encoding="utf-8")
    return BUCHONG_GT, BUCHONG_EXPECTED


# ---------------------------------------------------------------- 恒力工贸.pdf
# 电子 PDF 正式报价单：含税/未税混写；缺报 1 种物料（气缸 SC63×100）

HENGLI_ROWS = [
    # (名称, 规格, 单位, 数量, 单价, 交期, 税率备注)
    ("内六角螺钉", "M8*20", "件", 5000, 0.052, "5天", "含税13%"),
    ("深沟球轴承", "6204", "个", 50, 8.8, "10天", "未税"),
    ("球阀", "304不锈钢 DN15", "个", 10, 48, "15天", "含税13%"),
    ("工业吸尘器滤芯", "适配XX-2000", "个", 4, 66, "12天", "未税"),
    ("三相异步电机", "1.5kW", "台", 2, 1260, "25天", "含税13%"),
    ("聚氨酯同步带", "8M-720", "条", 10, 40, "7天", "未税"),
    ("接近开关", "M12 NPN 常开", "个", 20, 27, "现货", "含税13%"),
]


def gen_hengli_pdf():
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    title_style = ParagraphStyle("t", fontName="STSong-Light", fontSize=16, alignment=1)
    body_style = ParagraphStyle("b", fontName="STSong-Light", fontSize=10)

    header = ["序号", "物料名称", "规格型号", "单位", "数量", "单价(元)", "金额(元)", "交期", "税率"]
    rows = [header]
    gt_lines, exp_lines = [], []
    for i, (name, spec, unit, qty, price, lead, tax) in enumerate(HENGLI_ROWS, start=1):
        amount = round(qty * price, 2)
        rows.append([str(i), name, spec, unit, str(qty), _fmt_num(price), _fmt_num(amount), lead, tax])
        gt_lines.append({
            "item_name": name, "spec": spec, "quantity_raw": str(qty), "unit": unit,
            "unit_price_raw": _fmt_num(price), "amount_raw": _fmt_num(amount),
            "currency": "CNY", "tax_included": tax.startswith("含税"),
            "lead_time_raw": lead, "payment_terms": "货到付款", "remark": tax,
            "confidence": "high", "snippet_hint": name,
        })
        exp_lines.append({
            "item_name": name, "spec_contains": spec.split()[0],
            "quantity": qty, "unit_price": price,
        })

    table = Table(rows)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
    ]))
    doc = SimpleDocTemplate(str(FILES_DIR / "恒力工贸.pdf"), pagesize=A4)
    doc.build([
        Paragraph("恒力工贸有限公司 报价单", title_style),
        Spacer(1, 12),
        Paragraph("报价日期：2026-08-09　　付款方式：货到付款", body_style),
        Spacer(1, 8),
        table,
        Spacer(1, 8),
        Paragraph("以上报价有效期 15 天。恒力工贸有限公司 业务部", body_style),
    ])
    return gt_lines, exp_lines


# ---------------------------------------------------------------- OCR 样本共用

def _find_cjk_font() -> str:
    for p in (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
    ):
        if Path(p).exists():
            return p
    raise RuntimeError("找不到可用中文字体（macOS 系统字体）")


def _render_lines_image(lines: list[str], font_size: int = 30, pad: int = 50):
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(_find_cjk_font(), font_size)
    line_h = int(font_size * 1.8)
    width = max(font.getlength(line) for line in lines) + 2 * pad
    img = Image.new("RGB", (int(width), line_h * len(lines) + 2 * pad), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((pad, pad + i * line_h), line, font=font, fill="black")
    return img


# ---------------------------------------------------------------- 鑫源自动化.pdf
# 扫描 PDF：文本渲染成图片再合成 PDF，并刻意埋入 OCR 噪音（0/O、1/I 混淆）

XINYUAN_LINES = [
    "鑫源自动化科技有限公司 报价单",
    "序号 物料名称 规格型号 数量 单价 交期",
    "1 内六角螺钉 M8*20 5000件 0.051元 7天",
    "2 深沟球轴承 62O4 5O个 9.0元 10天",
    "3 球阀 304不锈钢DN15 10个 47元 15天",
    "4 工业吸尘器滤芯 适配XX-2000 4个 70元 20天",
    "5 三相异步电机 1.5kW 2台 1300元 30天",
    "6 聚氨酯同步带 8M-720 10条 41元 7天",
    "7 气缸 SC63*100 4个 l65元 12天",
    "8 接近开关 M12 NPN 常开 20个 26.5元 现货",
]

XINYUAN_ROWS = [
    # (名称, 规格, 单位, 数量原文, 数量真值, 单价原文, 单价真值, 交期, 是否噪音行)
    ("内六角螺钉", "M8*20", "件", "5000件", 5000, "0.051元", 0.051, "7天", False),
    ("深沟球轴承", "62O4", "个", "5O个", 50, "9.0元", 9.0, "10天", True),
    ("球阀", "304不锈钢DN15", "个", "10个", 10, "47元", 47, "15天", False),
    ("工业吸尘器滤芯", "适配XX-2000", "个", "4个", 4, "70元", 70, "20天", False),
    ("三相异步电机", "1.5kW", "台", "2台", 2, "1300元", 1300, "30天", False),
    ("聚氨酯同步带", "8M-720", "条", "10条", 10, "41元", 41, "7天", False),
    ("气缸", "SC63*100", "个", "4个", 4, "l65元", 165, "12天", True),
    ("接近开关", "M12 NPN 常开", "个", "20个", 20, "26.5元", 26.5, "现货", False),
]


def gen_xinyuan_scanned_pdf():
    from PIL import Image

    img = _render_lines_image(XINYUAN_LINES)
    img = img.rotate(1.2, resample=Image.BICUBIC, expand=True, fillcolor="white")  # 轻微歪斜
    img.save(FILES_DIR / "鑫源自动化.pdf", "PDF", resolution=300.0)

    gt_lines, exp_lines = [], []
    for name, spec, unit, qty_raw, qty, price_raw, price, lead, noisy in XINYUAN_ROWS:
        gt_lines.append({
            "item_name": name, "spec": spec, "quantity_raw": qty_raw, "unit": unit,
            "unit_price_raw": price_raw, "amount_raw": "", "currency": "CNY",
            "tax_included": None, "lead_time_raw": lead, "payment_terms": "",
            "remark": "OCR 文本，字符混淆" if noisy else "",
            "confidence": "low" if noisy else "high",
            "snippet_hint": name,
        })
        exp_lines.append({
            "item_name": name, "spec_contains": spec[:2],
            "quantity": qty, "unit_price": price,
        })
    return gt_lines, exp_lines


# ---------------------------------------------------------------- 广联轴承.png
# 拍照图片：表格图 + 透视畸变 + 轻微模糊

GUANGLIAN_ROWS = [
    ("内六角螺钉", "M8*20", "件", 5000, 0.049, "现货"),
    ("深沟球轴承", "6204", "个", 50, 8.0, "3天"),
    ("球阀", "304不锈钢DN15", "个", 10, 44, "一周"),
    ("工业吸尘器滤芯", "适配XX-2000", "个", 4, 72, "15天"),
    ("三相异步电机", "1.5kW", "台", 2, 1240, "现货"),
    ("聚氨酯同步带", "8M-720", "条", 10, 37, "5天"),
    ("气缸", "SC63*100", "个", 4, 160, "10天"),
    ("接近开关", "M12 NPN 常开", "个", 20, 24, "现货"),
]


def gen_guanglian_png():
    import cv2
    import numpy as np

    lines = ["广联轴承销售部 报价单", "物料名称 规格型号 单位 数量 单价 交期"] + [
        f"{name} {spec} {unit} {qty} {_fmt_num(price)} {lead}"
        for name, spec, unit, qty, price, lead in GUANGLIAN_ROWS
    ]
    img = _render_lines_image(lines, font_size=34)
    arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    h, w = arr.shape[:2]
    # 透视畸变（模拟手机斜拍）+ 轻微模糊
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[40, 25], [w - 60, 8], [w - 15, h - 35], [18, h - 12]])
    m = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(
        arr, m, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255)
    )
    blurred = cv2.GaussianBlur(warped, (3, 3), 0)
    cv2.imwrite(str(FILES_DIR / "广联轴承.png"), blurred)

    gt_lines, exp_lines = [], []
    for name, spec, unit, qty, price, lead in GUANGLIAN_ROWS:
        gt_lines.append({
            "item_name": name, "spec": spec, "quantity_raw": str(qty), "unit": unit,
            "unit_price_raw": _fmt_num(price), "amount_raw": "", "currency": "CNY",
            "tax_included": None, "lead_time_raw": lead, "payment_terms": "",
            "remark": "", "confidence": "high", "snippet_hint": name,
        })
        exp_lines.append({
            "item_name": name, "spec_contains": spec[:2],
            "quantity": qty, "unit_price": price,
        })
    return gt_lines, exp_lines


# ---------------------------------------------------------------- main

def main() -> None:
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    EXPECTED_DIR.mkdir(parents=True, exist_ok=True)

    generators = {
        "华东机电.xlsx": ("华东机电设备有限公司", gen_huadong_xlsx),
        "铭泰五交化.txt": ("铭泰五交化", gen_mingtai_txt),
        "华东机电-补充.txt": ("华东机电设备有限公司", gen_buchong_txt),
        "恒力工贸.pdf": ("恒力工贸有限公司", gen_hengli_pdf),
        "鑫源自动化.pdf": ("鑫源自动化科技有限公司", gen_xinyuan_scanned_pdf),
        "广联轴承.png": ("广联轴承销售部", gen_guanglian_png),
    }

    ground_truth = {}
    for filename, (supplier, fn) in generators.items():
        gt_lines, exp_lines = fn()
        ground_truth[filename] = {"supplier_name": supplier, "lines": gt_lines}
        (EXPECTED_DIR / f"{filename}.json").write_text(
            json.dumps(
                {
                    "source_file": filename,
                    "supplier_name_contains": "华东机电" if "华东" in supplier else supplier,
                    "lines": exp_lines,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"  生成 {filename}（{len(gt_lines)} 行）")

    (FIXTURES / "ground_truth.json").write_text(
        json.dumps(ground_truth, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"样本集生成完毕 -> {FILES_DIR}")


if __name__ == "__main__":
    main()
