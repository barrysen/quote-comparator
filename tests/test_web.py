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


def test_upload_without_key_rejected(monkeypatch):
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
