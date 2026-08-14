"""Web 后端：把 CLI 提取流水线包装成 HTTP 接口。

- POST /api/jobs            上传报价文件（multipart files）或 demo=true 跑内置样本，返回 job_id
- GET  /api/jobs/{id}       查询状态 / 日志 / 完成后的汇总与结果 JSON
- GET  /api/jobs/{id}/files/{kind}  下载产物（xlsx | json | report）
- GET  /api/health          环境与配置自检

每个任务在 output/web_jobs/{job_id}/ 下独立运行（中间产物、产物都在其中），
互不污染，也不影响 CLI 的 intermediates/ 缓存。
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from src.cli import cmd_extract
from src.config_loader import DEFAULT_SETTINGS, load_dotenv, load_settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
JOBS_ROOT = PROJECT_ROOT / "output" / "web_jobs"
DEMO_DIR = PROJECT_ROOT / "tests" / "fixtures" / "files"
DEMO_CONFIG = PROJECT_ROOT / "tests" / "fixtures" / "settings_test.yml"
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "settings.yml"
MODELS_FILE = PROJECT_ROOT / "config" / "models.yml"
MODELS_EXAMPLE = PROJECT_ROOT / "config" / "models.example.yml"

MAX_FILES = 30
ALLOWED_SUFFIXES = {".xlsx", ".xls", ".pdf", ".png", ".jpg", ".jpeg", ".txt", ".csv"}

app = FastAPI(title="报价单提取比价工具")

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


# ---------- 模型档案（config/models.yml，只读） ----------


def load_models() -> dict:
    """读取模型档案：models.yml（本机，gitignore）→ models.example.yml → settings.yml 兜底。"""
    import yaml

    source = MODELS_FILE if MODELS_FILE.exists() else MODELS_EXAMPLE
    if source.exists():
        data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        profiles = data.get("profiles") or []
    else:
        llm = load_settings(DEFAULT_CONFIG)["llm"]
        profiles = [
            {
                "name": "default",
                "label": "默认（settings.yml）",
                "base_url": llm["base_url"],
                "model": llm["model"],
                "api_key_env": llm["api_key_env"],
            }
        ]
        data = {}
    for p in profiles:  # 缺省 api_key_env：供运行时注入环境用
        p.setdefault("api_key_env", f"{str(p.get('name', 'llm')).upper()}_API_KEY")
    active = data.get("active") or profiles[0]["name"]
    if not any(p["name"] == active for p in profiles):
        active = profiles[0]["name"]
    return {"active": active, "profiles": profiles}


def get_profile(name: str | None) -> dict:
    models = load_models()
    name = name or models["active"]
    for p in models["profiles"]:
        if p["name"] == name:
            return p
    raise HTTPException(400, f"模型档案不存在: {name}")


def _profile_key(p: dict) -> str:
    """档案密钥：api_key 字段优先，其次环境变量 / .env。"""
    load_dotenv()
    return (p.get("api_key") or "").strip() or os.environ.get(p.get("api_key_env", ""), "")


def _profile_view(p: dict) -> dict:
    """接口视图：永不返回 api_key 本体，只返回是否已配置。"""
    return {
        "name": p["name"],
        "label": p.get("label") or p["name"],
        "base_url": p["base_url"],
        "model": p["model"],
        "api_key_env": p["api_key_env"],
        "key_configured": bool(_profile_key(p)),
    }


@app.get("/api/models")
def list_models() -> dict:
    models = load_models()
    return {
        "active": models["active"],
        "profiles": [_profile_view(p) for p in models["profiles"]],
    }


def _set_job(job_id: str, **fields) -> None:
    with _lock:
        _jobs[job_id].update(fields)


def _append_log(job_id: str, text: str) -> None:
    with _lock:
        _jobs[job_id]["log"] += text


class _LogWriter(io.TextIOBase):
    """把流水线 print 的进度实时并入任务日志。"""

    def __init__(self, job_id: str):
        self._job_id = job_id

    def write(self, s: str) -> int:
        if s:
            _append_log(self._job_id, s)
        return len(s)


def _run_job(job_id: str, folder: Path, config_path: Path, job_dir: Path, profile: dict | None) -> None:
    output = job_dir / "比价结果.xlsx"
    # 中间产物放到任务目录内，并强制重跑（任务之间不复用缓存）
    args = argparse.Namespace(
        folder=str(folder),
        output=str(output),
        config=str(config_path),
        force=True,
    )
    # cmd_extract 从 settings 读 intermediates_dir；用环境级覆盖最小侵入：
    # 直接 monkey-patch load_settings 太重，改为在任务目录写一份覆盖配置。
    try:
        import yaml

        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        cfg["intermediates_dir"] = str(job_dir / "intermediates")
        if profile:  # 用所选模型档案覆盖 llm 段
            llm = dict(cfg.get("llm") or {})
            llm.update(
                {
                    "base_url": profile["base_url"],
                    "model": profile["model"],
                    "api_key_env": profile["api_key_env"],
                }
            )
            cfg["llm"] = llm
            key = _profile_key(profile)
            if key:  # 档案里直写的 api_key 注入进程环境，供 LLM 客户端读取
                os.environ[profile["api_key_env"]] = key
            _append_log(job_id, f"使用模型档案: {profile['name']} ({profile['model']})\n")
        # units_file / prompts 是相对项目根的路径，保持 uvicorn 在项目根启动即可
        job_config = job_dir / "settings.yml"
        job_config.write_text(
            yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8"
        )
        args.config = str(job_config)

        buf = _LogWriter(job_id)
        with contextlib.redirect_stdout(buf):
            code = cmd_extract(args)
        if code != 0:
            _set_job(job_id, status="error", error="流水线执行失败，详见日志")
            return

        result_json = output.with_suffix(".result.json")
        summary = {}
        result = None
        if result_json.exists():
            result = json.loads(result_json.read_text(encoding="utf-8"))
            summary = {
                "suppliers": len(result.get("quotes", [])),
                "quote_lines": sum(len(q.get("lines", [])) for q in result.get("quotes", [])),
                "groups": len(result.get("comparison", {}).get("groups", [])),
                "missing": len(result.get("comparison", {}).get("missing", [])),
                "findings": len(result.get("findings", [])),
                "failed_files": len(result.get("failed_files", [])),
            }
        _set_job(job_id, status="done", summary=summary, result=result)
    except Exception as e:  # noqa: BLE001 - 任务失败要回传而不是崩进程
        _set_job(job_id, status="error", error=f"{type(e).__name__}: {e}")


@app.get("/api/health")
def health() -> dict:
    models = load_models()
    active = next(p for p in models["profiles"] if p["name"] == models["active"])
    return {
        "ok": True,
        "llm_configured": bool(_profile_key(active)),
        "llm_key_env": active["api_key_env"],
        "demo_available": DEMO_DIR.is_dir() and DEMO_CONFIG.exists(),
    }


@app.post("/api/jobs")
async def create_job(
    demo: bool = Form(False),
    model: str = Form(""),
    files: list[UploadFile] | None = File(None),
) -> dict:
    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    if demo:
        if not DEMO_DIR.is_dir():
            raise HTTPException(400, "演示样本不存在")
        folder = DEMO_DIR
        config_path = DEMO_CONFIG
        profile = None
    else:
        if not files:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(400, "请至少上传一个报价文件")
        try:
            profile = get_profile(model or None)
        except HTTPException:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise
        if not _profile_key(profile):
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(
                400,
                f"模型档案「{profile['name']}」未配置密钥；"
                f"请在 config/models.yml 的该档案中填写 api_key，"
                f"或在本机 .env / 环境变量中配置 {profile['api_key_env']}",
            )
        if len(files) > MAX_FILES:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(400, f"一次最多上传 {MAX_FILES} 个文件")
        folder = job_dir / "input"
        folder.mkdir(parents=True, exist_ok=True)
        for f in files:
            name = Path(f.filename or "").name
            if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
                shutil.rmtree(job_dir, ignore_errors=True)
                raise HTTPException(400, f"不支持的文件类型: {name}")
            (folder / name).write_bytes(await f.read())
        config_path = DEFAULT_CONFIG

    with _lock:
        _jobs[job_id] = {"status": "running", "log": "", "demo": demo}
    threading.Thread(
        target=_run_job, args=(job_id, folder, config_path, job_dir, profile), daemon=True
    ).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "任务不存在")
        return {"job_id": job_id, **job}


@app.get("/api/jobs/{job_id}/files/{kind}")
def job_file(job_id: str, kind: str) -> FileResponse:
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    if job.get("status") != "done":
        raise HTTPException(409, "任务尚未完成")
    job_dir = JOBS_ROOT / job_id
    mapping = {
        "xlsx": job_dir / "比价结果.xlsx",
        "json": job_dir / "比价结果.result.json",
        "report": job_dir / "比价结果.report.txt",
    }
    path = mapping.get(kind)
    if path is None:
        raise HTTPException(404, "未知的产物类型")
    if not path.exists():
        raise HTTPException(404, "产物文件不存在")
    return FileResponse(path, filename=path.name)
