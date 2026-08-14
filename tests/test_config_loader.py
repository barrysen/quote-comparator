"""config_loader.load_dotenv 测试。"""

from __future__ import annotations

import os

from src.config_loader import load_dotenv


def test_dotenv_loaded(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        '# 注释\nDEEPSEEK_API_KEY=sk-test123\nQUOTED="sk-quoted"\n\nBADLINE\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)
    load_dotenv(env)
    assert os.environ["DEEPSEEK_API_KEY"] == "sk-test123"
    assert os.environ["QUOTED"] == "sk-quoted"


def test_dotenv_does_not_override_existing(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("DEEPSEEK_API_KEY=sk-from-file\n", encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-shell")
    load_dotenv(env)
    assert os.environ["DEEPSEEK_API_KEY"] == "sk-from-shell"


def test_dotenv_missing_file_ok(tmp_path):
    load_dotenv(tmp_path / "nonexistent.env")  # 不抛异常
