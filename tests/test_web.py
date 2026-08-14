"""Web 后端接口测试（src/web/app.py）。

演示模式跑内置 fixtures + replay，无需 API Key。
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from src.web.app import app

client = TestClient(app)


def _wait_done(job_id: str, timeout: float = 180.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200
        job = r.json()
        if job["status"] != "running":
            return job
        time.sleep(1.0)
    pytest.fail("任务超时未完成")


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["demo_available"] is True


def test_demo_job_completes():
    r = client.post("/api/jobs", data={"demo": "true"})
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    job = _wait_done(job_id)
    assert job["status"] == "done", job.get("error")
    assert job["summary"]["suppliers"] >= 3
    assert job["summary"]["quote_lines"] > 0
    assert job["result"]["comparison"]["groups"]

    # 产物可下载
    for kind in ("xlsx", "json", "report"):
        fr = client.get(f"/api/jobs/{job_id}/files/{kind}")
        assert fr.status_code == 200, kind
        assert len(fr.content) > 100


def test_upload_without_key_rejected(tmp_path, monkeypatch):
    import src.web.app as webapp

    # 与本机真实的 config/models.yml 隔离：使用无密钥的档案
    mf = tmp_path / "models.yml"
    mf.write_text(
        """
active: deepseek
profiles:
  - name: deepseek
    base_url: "https://api.deepseek.com/v1"
    model: "deepseek-chat"
    api_key_env: "DEEPSEEK_API_KEY"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(webapp, "MODELS_FILE", mf)
    monkeypatch.setattr(webapp, "MODELS_EXAMPLE", tmp_path / "nonexistent.yml")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    content = "供应商: 测试五金\n螺丝 M6x20 1000 个 0.05 元/个\n".encode("utf-8")
    r = client.post(
        "/api/jobs",
        files=[("files", ("测试五金.txt", content, "text/plain"))],
    )
    assert r.status_code == 400
    assert "DEEPSEEK_API_KEY" in r.json()["detail"]


def test_upload_rejects_bad_suffix():
    r = client.post(
        "/api/jobs",
        files=[("files", ("evil.exe", b"xx", "application/octet-stream"))],
    )
    assert r.status_code == 400


def test_unknown_job_404():
    assert client.get("/api/jobs/nonexistent").status_code == 404


# ---------- 模型档案（config/models.yml，只读） ----------


def test_models_config(tmp_path, monkeypatch):
    import src.web.app as webapp

    mf = tmp_path / "models.yml"
    mf.write_text(
        """
active: kimi
profiles:
  - name: deepseek
    label: DeepSeek Chat
    base_url: "https://api.deepseek.com/v1"
    model: "deepseek-chat"
    api_key_env: "DEEPSEEK_API_KEY"
  - name: kimi
    label: Kimi K2
    base_url: "https://api.moonshot.cn/v1"
    model: "kimi-k2-0905-preview"
    api_key_env: "MOONSHOT_API_KEY"
  - name: local
    base_url: "http://127.0.0.1:9999/v1"
    model: "local-llm"
    api_key: "sk-direct-test-key"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(webapp, "MODELS_FILE", mf)

    # 列出档案与默认项
    r = client.get("/api/models")
    assert r.status_code == 200
    data = r.json()
    assert [p["name"] for p in data["profiles"]] == ["deepseek", "kimi", "local"]
    assert data["active"] == "kimi"

    # 直写 api_key 的档案视为已配置，且响应绝不泄露 Key 本体
    local = next(p for p in data["profiles"] if p["name"] == "local")
    assert local["key_configured"] is True
    assert local["label"] == "local"  # 未填 label 时回退为档案名，页面不会出现空显示
    assert "sk-direct-test-key" not in r.text

    # 缺密钥时创建真实任务被拒，错误信息带档案名与环境变量名
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    r = client.post(
        "/api/jobs",
        data={"model": "kimi"},
        files=[("files", ("a.txt", b"x", "text/plain"))],
    )
    assert r.status_code == 400
    assert "MOONSHOT_API_KEY" in r.json()["detail"]

    # 直写 api_key 的档案可通过密钥检查、任务被受理
    r = client.post(
        "/api/jobs",
        data={"model": "local"},
        files=[("files", ("a.txt", b"x", "text/plain"))],
    )
    assert r.status_code == 200

    # 未知档案
    r = client.post(
        "/api/jobs",
        data={"model": "ghost"},
        files=[("files", ("a.txt", b"x", "text/plain"))],
    )
    assert r.status_code == 400


def test_models_fallback_without_file(tmp_path, monkeypatch):
    """models.yml 不存在时回退到 models.example.yml / settings.yml。"""
    import src.web.app as webapp

    monkeypatch.setattr(webapp, "MODELS_FILE", tmp_path / "nonexistent.yml")
    data = client.get("/api/models").json()
    assert len(data["profiles"]) >= 1
    assert data["active"] == data["profiles"][0]["name"]
