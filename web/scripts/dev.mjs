// 一键启动：FastAPI 后端（8321）+ Vite 前端
// 用法：npm run dev -- [--host 0.0.0.0] [--port 3000]（参数原样转发给 vite）
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const webDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const projectRoot = path.resolve(webDir, "..");
const python = path.join(projectRoot, ".venv", "bin", "python");

let shuttingDown = false;
const children = [];

function killAll() {
  shuttingDown = true;
  for (const c of children) {
    try { c.kill("SIGTERM"); } catch {}
  }
}

process.on("SIGINT", () => { killAll(); process.exit(0); });
process.on("SIGTERM", () => { killAll(); process.exit(0); });

const backend = spawn(
  python,
  ["-m", "uvicorn", "src.web.app:app", "--host", "127.0.0.1", "--port", "8321"],
  { cwd: projectRoot, stdio: "inherit" }
);
children.push(backend);
backend.on("exit", (code) => {
  if (!shuttingDown) {
    console.error(`[dev] 后端退出 (code=${code})，前端随之停止`);
    killAll();
    process.exit(code ?? 1);
  }
});

const viteBin = path.join(webDir, "node_modules", ".bin", "vite");
const frontend = spawn(viteBin, process.argv.slice(2), {
  cwd: webDir,
  stdio: "inherit",
});
children.push(frontend);
frontend.on("exit", (code) => {
  if (!shuttingDown) {
    killAll();
    process.exit(code ?? 0);
  }
});
