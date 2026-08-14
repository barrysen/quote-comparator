"""配置加载：settings.yml（深合并默认值）+ units.yml（反向映射）+ .env（本机密钥）。"""

from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml


def load_dotenv(path: str | Path = ".env") -> None:
    """极简 .env 加载：KEY=VALUE 逐行写入环境变量（已存在的不覆盖）。

    让 API Key 只存在于本机 .env（gitignore 忽略），CLI 与 Web 共用。
    """
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

DEFAULT_SETTINGS: dict = {
    "llm": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "model": "deepseek-chat",
        "temperature": 0,
        "timeout": 60,
        "max_retries": 3,
        "retry_delay": 1.0,
        "structured_mode": "json_schema",
        "context_chars": 60000,
        "replay_dir": None,
    },
    "ocr": {"engine": "auto", "dpi": 300, "min_char_confidence": 0.85},
    "compare": {
        "price_deviation_threshold": 0.15,
        "amount_tolerance": 0.02,
        "lead_time_factor": 2.0,
    },
    "intermediates_dir": "intermediates",
    "units_file": "config/units.yml",
    "prompts": {
        "parse_quote": "config/prompts/parse_quote.md",
        "match_items": "config/prompts/match_items.md",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_settings(path: str | Path | None) -> dict:
    """加载 settings.yml 并与默认值深合并；path 为 None 时直接返回默认值。"""
    if path is None:
        return copy.deepcopy(DEFAULT_SETTINGS)
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"配置文件不存在: {p}")
    user = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return _deep_merge(DEFAULT_SETTINGS, user)


def load_units(path: str | Path) -> dict[str, str]:
    """加载 units.yml，返回 {别名(小写): 标准单位} 反向映射（含标准单位自身）。"""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    reverse: dict[str, str] = {}
    for std, aliases in raw.items():
        reverse[str(std).strip().lower()] = str(std).strip()
        for alias in aliases or []:
            reverse[str(alias).strip().lower()] = str(std).strip()
    return reverse
