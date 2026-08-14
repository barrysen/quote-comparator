"""CLI 入口。

用法:
    python -m src.cli extract ./报价文件夹 -o 比价结果.xlsx [--config config/settings.yml] [--force]

每个阶段的输出写入 intermediates/{文件名}/{阶段}.json，存在则跳过（--force 重跑）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from src.config_loader import load_settings
from src.llm.client import LLMClient
from src.models import ClassifyResult, Comparison, RawContent, SupplierQuote
from src.pipeline import classify, compare, export, extract_raw, parse_quote, validate

STAGE_CLASSIFY = "01_classify"
STAGE_RAW = "02_raw"
STAGE_QUOTE = "03_quote"
STAGE_VALIDATED = "04_validated"
STAGE_COMPARE = "_compare"


def _safe_name(filename: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", filename)


def _cache_path(base: Path, source_file: str, stage: str) -> Path:
    return base / _safe_name(source_file) / f"{stage}.json"


def _load_cached(path: Path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _save_cache(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_extract(args: argparse.Namespace) -> int:
    try:
        config = load_settings(args.config)
    except FileNotFoundError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"错误: 不是文件夹: {folder}", file=sys.stderr)
        return 2

    intermediates = Path(config["intermediates_dir"])
    files = sorted(
        p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")
    )
    print(f"发现 {len(files)} 个文件，开始处理...")

    llm = LLMClient(config)
    quotes: list[SupplierQuote] = []
    findings = []
    failed_files: list[dict] = []
    failed_raw: list[dict] = []

    for path in files:
        name = path.name
        print(f"  -> {name}")

        # 阶段一：格式分拣
        c_path = _cache_path(intermediates, name, STAGE_CLASSIFY)
        cached = None if args.force else _load_cached(c_path)
        if cached is not None:
            c = ClassifyResult.model_validate(cached)
        else:
            c = classify.run({"file": str(path)}, config)
            _save_cache(c_path, c)
        if c.kind == "unsupported":
            failed_files.append({"file": name, "reason": f"不支持的格式: {c.detail}"})
            continue

        # 阶段二：原始内容提取
        r_path = _cache_path(intermediates, name, STAGE_RAW)
        cached = None if args.force else _load_cached(r_path)
        if cached is not None:
            raw = RawContent.model_validate(cached)
        else:
            raw = extract_raw.run(c, config)
            _save_cache(r_path, raw)

        # 阶段三：LLM 结构化解析
        q_path = _cache_path(intermediates, name, STAGE_QUOTE)
        cached = None if args.force else _load_cached(q_path)
        if cached is not None:
            quote = SupplierQuote.model_validate(cached)
        else:
            quote = parse_quote.run(raw, config, llm)
            _save_cache(q_path, quote)

        # 阶段四：规则校验
        v_path = _cache_path(intermediates, name, STAGE_VALIDATED)
        cached = None if args.force else _load_cached(v_path)
        if cached is not None:
            quote = SupplierQuote.model_validate(cached["quote"])
            file_findings = cached["findings"]
        else:
            quote, file_findings_obj = validate.run(quote, config, raw_text=raw.raw_text)
            file_findings = [f.model_dump(mode="json") for f in file_findings_obj]
            _save_cache(v_path, {
                "quote": quote.model_dump(mode="json"), "findings": file_findings,
            })
        findings.extend(file_findings)
        quotes.append(quote)

        if any(w.startswith("LLM_FAILED") for w in quote.warnings):
            failed_files.append({"file": name, "reason": "LLM 解析失败（原文见 解析失败原文 Sheet）"})
            failed_raw.append({"file": name, "raw_text": raw.raw_text})

    # 阶段五：比价分析（跨文件，单独缓存；任一上游变化需 --force 重跑）
    cmp_path = intermediates / f"{STAGE_COMPARE}.json"
    cached = None if args.force else _load_cached(cmp_path)
    if cached is not None:
        comparison = Comparison.model_validate(cached)
    else:
        comparison = compare.run(
            {"quotes": [q.model_dump(mode="json") for q in quotes]}, config, llm
        )
        _save_cache(cmp_path, comparison)

    # 阶段六：导出
    result = export.run(
        {
            "quotes": [q.model_dump(mode="json") for q in quotes],
            "findings": findings,
            "failed_files": failed_files,
            "failed_raw": failed_raw,
            "comparison": comparison.model_dump(mode="json"),
            "output": str(Path(args.output)),
        },
        config,
    )

    total_lines = sum(len(q.lines) for q in quotes)
    print(f"\n完成: {len(quotes)} 个文件，{total_lines} 条报价行，{len(comparison.groups)} 组物料，{len(comparison.missing)} 条缺报，{len(findings)} 条校验发现，{len(failed_files)} 个失败")
    print(f"  Excel : {result['xlsx']}")
    print(f"  JSON  : {result['result_json']}")
    print(f"  报告  : {result['report']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="quote-comparator", description="报价单提取比价工具"
    )
    sub = p.add_subparsers(dest="command", required=True)
    e = sub.add_parser("extract", help="批量提取一个文件夹的报价文件并生成比价 Excel")
    e.add_argument("folder", help="报价文件所在文件夹")
    e.add_argument("-o", "--output", required=True, help="输出 Excel 路径")
    e.add_argument("--config", default="config/settings.yml", help="配置文件路径")
    e.add_argument("--force", action="store_true", help="忽略中间产物缓存，全部重跑")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "extract":
        return cmd_extract(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
