"""LLM 客户端单测：重试 / JSON 提取 / 离线回放。全程 mock transport，不依赖网络。"""

import json

import pytest

from src.llm.client import LLMClient, LLMError, ReplayTransport, _extract_json, build_request


def _cfg(**over):
    llm = {
        "base_url": "http://unused",
        "api_key_env": "UNUSED_KEY",
        "model": "m",
        "temperature": 0,
        "timeout": 1,
        "max_retries": 3,
        "retry_delay": 0,
        "structured_mode": "json_schema",
        "context_chars": 60000,
        "replay_dir": None,
    }
    llm.update(over)
    return {"llm": llm}


SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}


class TestExtractJson:
    def test_plain(self):
        assert _extract_json('{"a": "1"}') == {"a": "1"}

    def test_fenced(self):
        assert _extract_json('```json\n{"a": "1"}\n```') == {"a": "1"}

    def test_surrounding_text(self):
        assert _extract_json('结果如下：\n{"a": "1"}\n完毕') == {"a": "1"}

    def test_not_json(self):
        with pytest.raises(LLMError):
            _extract_json("没有任何 JSON")


class TestRetry:
    def test_success_after_two_failures(self):
        calls = []

        def transport(messages, rf, cfg):
            calls.append(1)
            if len(calls) < 3:
                raise ConnectionError("boom")
            return '{"a": "ok"}'

        client = LLMClient(_cfg(), transport=transport)
        assert client.complete_json(system="s", user="u", schema_name="t", schema=SCHEMA) == {"a": "ok"}
        assert len(calls) == 3

    def test_exhausted(self):
        def transport(messages, rf, cfg):
            raise ConnectionError("boom")

        client = LLMClient(_cfg(), transport=transport)
        with pytest.raises(LLMError, match="重试 3 次"):
            client.complete_json(system="s", user="u", schema_name="t", schema=SCHEMA)

    def test_unparseable_after_retries(self):
        client = LLMClient(_cfg(), transport=lambda m, r, c: "不是 JSON")
        with pytest.raises(LLMError):
            client.complete_json(system="s", user="u", schema_name="t", schema=SCHEMA)


class TestReplay:
    def test_hit_and_miss(self, tmp_path):
        cfg = _cfg()["llm"]
        messages, rf = build_request("sys", "usr", "t", SCHEMA, cfg)
        key = ReplayTransport.key_for(messages, rf)
        (tmp_path / f"{key}.json").write_text(
            json.dumps({"response": '{"a": "replayed"}'}), encoding="utf-8"
        )
        client = LLMClient(_cfg(replay_dir=str(tmp_path)))
        assert client.complete_json(system="sys", user="usr", schema_name="t", schema=SCHEMA) == {
            "a": "replayed"
        }
        # 换一个 user → 哈希不同 → replay 缺失
        with pytest.raises(LLMError, match="replay 缺失|重试"):
            client.complete_json(system="sys", user="别的", schema_name="t", schema=SCHEMA)
