# 开发文档

> 面向开发者的进度与内部约定。用户向介绍见 `README.md`，需求池见 `BACKLOG.md`。

## 当前进度

- **v1.0 全部里程碑（M1~M5）完成**，设计方案 §7 验收标准全部通过（153 项测试）。
- 在 CLI 之外新增 Web UI（`web/` + `src/web/app.py`）：功能介绍、上传提取、比价矩阵预览、产物下载、演示模式。

## 已知偏差

- **OCR 引擎（与设计方案 §2.2 的偏差）**：设计选型 PaddleOCR；开发环境 PaddlePaddle wheel
  下载受限，当前默认使用 rapidocr-onnxruntime（同一 PP-OCR 模型家族，ONNX 轻量推理）。
  `src/pipeline/ocr.py` 按引擎可插拔实现：装好 `paddlepaddle + paddleocr` 后
  `settings.yml` 的 `ocr.engine` 保持 `auto` 即自动优先 PaddleOCR，无需改代码。

## 开发

```bash
.venv/bin/python -m pytest            # 全量测试（含 e2e，走 replay 离线回放，无需 API Key）
.venv/bin/python tests/fixtures/generate.py     # 重新生成虚拟样本集
.venv/bin/python tests/fixtures/make_replay.py  # 重新生成 replay 响应（改了 prompt 或样本后）
```

### 新增样本

1. 在 `tests/fixtures/generate.py` 里添加生成函数与 ground truth（含 `snippet_hint`）；
2. 依次运行 `generate.py` 与 `make_replay.py`；
3. 在 `tests/fixtures/expected/` 中补充/核对期望关键字段，`tests/test_e2e.py` 会自动纳入准确率统计。

### 准确率口径

```
字段准确率 = 1 - (值错误且未标黄的关键字段数 / 关键字段总数)
```

核心承诺：**允许错，但不允许错了不告诉你** —— 错了但标黄供人工复核不算事故。

## 项目结构

```
config/               settings.yml / units.yml / prompts（LLM prompt 可编辑）
src/
  cli.py              extract 子命令 + 中间产物缓存（断点续跑）
  web/app.py          Web 后端（FastAPI）：任务制包装 CLI 流水线，产物按任务隔离在 output/web_jobs/
  models.py           pydantic 数据模型（设计方案 §4）
  llm/client.py       唯一 LLM 入口：重试/超时/JSON Schema/离线回放
  pipeline/
    classify.py       阶段一 格式分拣
    extract_raw.py    阶段二 原始内容提取（统一为保留结构的文本）
    ocr.py            阶段二子模块 OCR 管线（引擎可插拔 + OpenCV 矫正）
    parse_quote.py    阶段三 LLM 结构化解析 + H1 溯源硬校验 + OCR 低置信硬标黄
    validate.py       阶段四 规则校验 V1~V7 全量
    compare.py        阶段五 物料对齐（规则 + LLM 保守兜底）与比价统计
    export.py         阶段六 Excel 导出（比价总表五色标色 / 明细 / 统计与异常）
tests/
  fixtures/           虚拟样本集（generate.py 可复现生成）+ expected + replay
  test_*.py           各阶段单测 + test_e2e.py 端到端回归 + test_web.py Web 接口
web/                  Web 前端（Vite + React + Tailwind + shadcn/ui），npm run dev 同时拉起后端
docs/screenshots/     README 引用的界面截图
intermediates/        CLI 中间产物缓存
output/               输出目录（web_jobs/ 为 Web 任务产物）
```

## 接口契约（见设计方案 §6）

1. 每个 `pipeline/*.py` 暴露纯函数 `run(input, config) -> output`，模块间禁止共享全局状态；
2. LLM 只允许经 `llm/client.py` 调用，其余模块禁止 import openai；
3. 校验规则签名统一 `check(quote, ctx) -> list[Finding]`；
4. 所有金额/数量的计算只发生在规则与比价阶段，LLM 输出层禁止出现计算值。
