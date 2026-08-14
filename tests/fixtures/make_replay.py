"""根据 ground_truth.json 生成 LLM 离线回放响应（replay）。

无网络 / 无 API Key 时，e2e 测试与演示通过 replay 驱动阶段三与阶段五：
- 阶段三回放响应 = 人工核对过的正确提取结果（即 ground truth），
  source_snippet 从真实 raw_text 中检索取得，保证 H1 溯源硬校验可通过；
- 阶段五物料对齐回放响应 = 按 MATCH_KEYWORDS 共享关键词判定（样本集内确定）。

用法:
    python tests/fixtures/make_replay.py            # 先生成样本（generate.py）
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent
PROJECT_ROOT = FIXTURES.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_settings  # noqa: E402
from src.llm.client import LLMClient, ReplayTransport, build_request  # noqa: E402
from src.models import RawContent  # noqa: E402
from src.pipeline import classify, compare, extract_raw, parse_quote, validate  # noqa: E402
from src.pipeline.parse_quote import QUOTE_SCHEMA, SCHEMA_NAME, SYSTEM_PROMPT  # noqa: E402

REPLAY_DIR = FIXTURES / "replay"

# 阶段五回放判定规则：两条描述共享以下任一关键词即判同一物料（虚拟样本集内人工核对）
MATCH_KEYWORDS = ["内六角螺钉", "深沟球轴承", "6204", "球阀", "滤芯", "电机", "同步带", "气缸", "接近开关"]


def _find_snippet(raw_text: str, hint: str) -> str:
    """在 raw_text 中找到包含 hint 的整行，作为 source_snippet（真实子串）。"""
    for line in raw_text.splitlines():
        if hint in line:
            return line.strip()
    raise ValueError(f"raw_text 中找不到 snippet 锚点: {hint!r}")


def _load_config() -> dict:
    config = load_settings(PROJECT_ROOT / "config" / "settings.yml")
    # prompt / units 路径绝对化，保证子进程任意 cwd 下可运行
    for key in ("parse_quote", "match_items"):
        config["prompts"][key] = str(PROJECT_ROOT / config["prompts"][key])
    config["units_file"] = str(PROJECT_ROOT / config["units_file"])
    return config


def _write_parse_replays(config: dict, ground_truth: dict) -> None:
    template = Path(config["prompts"]["parse_quote"]).read_text(encoding="utf-8")
    for filename, truth in ground_truth.items():
        sample = FIXTURES / "files" / filename
        c = classify.run({"file": str(sample)}, config)
        raw = extract_raw.run(c, config)
        if not raw.raw_text.strip():
            # OCR 引擎不可用等场景：阶段三不会调用 LLM，无需录制回放
            print(f"  跳过 {filename}（无可用文本: {raw.extraction_warnings[:1]}）")
            continue
        user = template.replace("{{file_name}}", filename).replace(
            "{{raw_text}}", raw.raw_text
        )
        messages, rf = build_request(
            SYSTEM_PROMPT, user, SCHEMA_NAME, QUOTE_SCHEMA, config["llm"]
        )
        key = ReplayTransport.key_for(messages, rf)

        lines = []
        try:
            for gt_line in truth["lines"]:
                line = {k: v for k, v in gt_line.items() if k != "snippet_hint"}
                line["source_snippet"] = _find_snippet(raw.raw_text, gt_line["snippet_hint"])
                lines.append(line)
        except ValueError as e:
            # OCR 实际输出与预期锚点不符（如噪音行）→ 跳过该文件并明示
            print(f"  跳过 {filename}（锚点未命中: {e}）")
            continue
        response = {"supplier_name": truth["supplier_name"], "lines": lines}

        (REPLAY_DIR / f"{key}.json").write_text(
            json.dumps(
                {"source_file": filename, "response": json.dumps(response, ensure_ascii=False)},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"  replay {key}.json <- {filename}（解析）")


def _write_match_replay(config: dict, ground_truth: dict) -> None:
    """用阶段三的回放跑通前四阶段，再为物料对齐请求录制响应。"""
    replay_cfg = copy.deepcopy(config)
    replay_cfg["llm"]["replay_dir"] = str(REPLAY_DIR)
    llm = LLMClient(replay_cfg)

    quotes = []
    for filename in ground_truth:
        sample = FIXTURES / "files" / filename
        c = classify.run({"file": str(sample)}, config)
        raw = extract_raw.run(c, config)
        quote = parse_quote.run(RawContent.model_validate(raw), replay_cfg, llm)
        quote, _ = validate.run(quote, replay_cfg)
        quotes.append(quote)

    req = compare.build_match_request(quotes, replay_cfg)
    if req is None:
        print("  物料对齐无候选对，跳过回放录制")
        return
    user, pairs, _, _ = req
    results = []
    for p in pairs:
        same = any(k in p["a"] and k in p["b"] for k in MATCH_KEYWORDS)
        results.append({
            "id": p["id"],
            "same": same,
            "confidence": "high",
            "reason": "共享关键词" if same else "名称与规格均不对应",
        })
    messages, rf = build_request(
        compare.MATCH_SYSTEM, user, compare.MATCH_SCHEMA_NAME,
        compare.MATCH_SCHEMA, config["llm"],
    )
    key = ReplayTransport.key_for(messages, rf)
    (REPLAY_DIR / f"{key}.json").write_text(
        json.dumps(
            {"source_file": "(物料对齐)", "response": json.dumps({"results": results}, ensure_ascii=False)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  replay {key}.json <- 物料对齐（{len(pairs)} 对候选）")


def main() -> None:
    gt_path = FIXTURES / "ground_truth.json"
    if not gt_path.exists():
        raise SystemExit("请先运行 tests/fixtures/generate.py 生成样本与真值")
    ground_truth = json.loads(gt_path.read_text(encoding="utf-8"))
    config = _load_config()
    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    _write_parse_replays(config, ground_truth)
    _write_match_replay(config, ground_truth)
    print(f"回放响应生成完毕 -> {REPLAY_DIR}")


if __name__ == "__main__":
    main()

