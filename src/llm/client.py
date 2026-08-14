"""统一的 LLM 客户端：重试 / 超时 / JSON Schema / 离线回放。

设计方案硬性约束：LLM 只允许经本模块调用，其余模块禁止 import openai。

Transport 抽象：transport(messages, response_format, llm_cfg) -> 响应文本。
- 默认走 OpenAI 兼容接口（端点可在 settings.yml 一键切换）；
- 配置 llm.replay_dir 时走离线回放（按请求内容哈希读取录制响应）；
- 测试可直接注入自定义 transport。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Callable, Optional


class LLMError(Exception):
    """LLM 调用最终失败（重试耗尽 / replay 缺失 / 返回不可解析）。"""


Transport = Callable[[list[dict], Optional[dict], dict], str]


def build_request(
    system: str, user: str, schema_name: str, schema: dict, llm_cfg: dict
) -> tuple[list[dict], Optional[dict]]:
    """构造消息与 response_format。导出给 replay 录制脚本复用，保证哈希一致。"""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    mode = llm_cfg.get("structured_mode", "json_schema")
    if mode == "json_schema":
        rf: Optional[dict] = {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "schema": schema, "strict": True},
        }
    elif mode == "json_object":
        rf = {"type": "json_object"}
    else:
        rf = None
    return messages, rf


def _extract_json(text: str) -> dict:
    """从 LLM 响应文本中提取 JSON 对象（容忍 ```json 围栏与前后杂文本）。"""
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        if "\n" in s:
            s = s.split("\n", 1)[1]
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMError(f"LLM 返回不含 JSON 对象: {text[:200]!r}")
    try:
        return json.loads(s[start : end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"LLM 返回 JSON 解析失败: {e}") from e


class OpenAITransport:
    """OpenAI 兼容接口（DeepSeek API / 本地 vLLM 等）。"""

    def __init__(self, cfg: dict):
        from openai import OpenAI  # 延迟导入，允许仅回放模式下无 openai 环境

        api_key = os.environ.get(cfg.get("api_key_env", "OPENAI_API_KEY"), "")
        if not api_key:
            raise LLMError(
                f"未配置 API Key：请设置环境变量 {cfg.get('api_key_env', 'OPENAI_API_KEY')}，"
                "或在 settings.yml 配置 llm.replay_dir 使用离线回放"
            )
        self.client = OpenAI(
            base_url=cfg["base_url"], api_key=api_key, timeout=cfg.get("timeout", 60)
        )
        self.model = cfg["model"]
        self.temperature = cfg.get("temperature", 0)

    def __call__(self, messages: list[dict], response_format: Optional[dict], cfg: dict) -> str:
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if response_format:
            kwargs["response_format"] = response_format
        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""


class ReplayTransport:
    """离线回放：按请求内容哈希读取录制的响应，用于无网络测试 / 演示。"""

    def __init__(self, replay_dir: str | Path):
        self.dir = Path(replay_dir)

    @staticmethod
    def key_for(messages: list[dict], response_format: Optional[dict]) -> str:
        payload = json.dumps(
            {"messages": messages, "rf": response_format},
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def path_for(self, messages: list[dict], response_format: Optional[dict]) -> Path:
        return self.dir / f"{self.key_for(messages, response_format)}.json"

    def __call__(self, messages: list[dict], response_format: Optional[dict], cfg: dict) -> str:
        path = self.path_for(messages, response_format)
        if not path.exists():
            raise LLMError(f"replay 缺失: {path}（请先运行 tests/fixtures/make_replay.py）")
        data = json.loads(path.read_text(encoding="utf-8"))
        return data["response"]


class LLMClient:
    """唯一 LLM 入口。complete_json 自带指数退避重试与 JSON 解析。"""

    def __init__(self, config: dict, transport: Optional[Transport] = None):
        self.cfg = config["llm"]
        if transport is not None:
            self.transport: Transport = transport
        elif self.cfg.get("replay_dir"):
            self.transport = ReplayTransport(self.cfg["replay_dir"])
        else:
            self.transport = OpenAITransport(self.cfg)

    def complete_json(self, *, system: str, user: str, schema_name: str, schema: dict) -> dict:
        messages, rf = build_request(system, user, schema_name, schema, self.cfg)
        attempts = int(self.cfg.get("max_retries", 3))
        delay = float(self.cfg.get("retry_delay", 1.0))
        last: Optional[Exception] = None
        for i in range(attempts):
            try:
                return _extract_json(self.transport(messages, rf, self.cfg))
            except Exception as e:  # noqa: BLE001 —— 任何失败都进入退避重试
                last = e
                if i < attempts - 1 and delay > 0:
                    time.sleep(delay * (2**i))
        raise LLMError(f"LLM 调用失败（已重试 {attempts} 次）: {last}")
