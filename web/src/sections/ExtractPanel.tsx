import { useRef, useState } from "react";
import { Upload, Play, FlaskConical, X, Loader2 } from "lucide-react";
import type { Health } from "../types/api";

interface Props {
  health: Health | null;
  running: boolean;
  log: string;
  onRunFiles: (files: File[]) => void;
  onRunDemo: () => void;
}

const ACCEPT = ".xlsx,.xls,.pdf,.png,.jpg,.jpeg,.txt,.csv";

export default function ExtractPanel({ health, running, log, onRunFiles, onRunDemo }: Props) {
  const [files, setFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = (list: FileList | null) => {
    if (!list) return;
    setFiles((prev) => {
      const names = new Set(prev.map((f) => f.name));
      const next = [...prev];
      for (const f of Array.from(list)) {
        if (!names.has(f.name)) next.push(f);
      }
      return next.slice(0, 30);
    });
  };

  return (
    <section id="extract" className="border-t border-neutral-200 bg-[#FAFAF7]">
      <div className="mx-auto max-w-6xl px-6 py-16">
        <p className="text-xs font-semibold tracking-[0.2em] text-orange-700">上手用</p>
        <h2 className="mt-2 text-2xl font-bold tracking-tight text-neutral-900">上传报价文件，一键提取比价</h2>

        <div className="mt-8 grid gap-8 lg:grid-cols-5">
          {/* 左：上传 */}
          <div className="lg:col-span-3">
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => { e.preventDefault(); setDragOver(false); addFiles(e.dataTransfer.files); }}
              onClick={() => inputRef.current?.click()}
              className={`flex min-h-44 cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 text-center transition-colors ${
                dragOver ? "border-orange-600 bg-orange-50" : "border-neutral-300 bg-white hover:border-neutral-400"
              }`}
            >
              <Upload className="h-6 w-6 text-neutral-500" strokeWidth={1.5} />
              <p className="mt-3 text-sm font-medium text-neutral-700">拖拽报价文件到这里，或点击选择</p>
              <p className="mt-1 text-xs text-neutral-400">支持 Excel / PDF / 图片 / 文本，一次最多 30 个</p>
              <input
                ref={inputRef}
                type="file"
                multiple
                accept={ACCEPT}
                className="hidden"
                onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }}
              />
            </div>

            {files.length > 0 && (
              <ul className="mt-4 divide-y divide-neutral-100 rounded-lg border border-neutral-200 bg-white">
                {files.map((f) => (
                  <li key={f.name} className="flex items-center justify-between px-4 py-2 text-sm">
                    <span className="truncate text-neutral-700">{f.name}</span>
                    <span className="ml-4 flex shrink-0 items-center gap-3 text-xs text-neutral-400">
                      {(f.size / 1024).toFixed(0)} KB
                      <button
                        onClick={() => setFiles((prev) => prev.filter((x) => x.name !== f.name))}
                        className="text-neutral-400 hover:text-neutral-700"
                        aria-label={`移除 ${f.name}`}
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </span>
                  </li>
                ))}
              </ul>
            )}

            <div className="mt-5 flex flex-wrap items-center gap-3">
              <button
                disabled={running || files.length === 0}
                onClick={() => onRunFiles(files)}
                className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                开始提取（{files.length} 个文件）
              </button>
              {health?.demo_available && (
                <button
                  disabled={running}
                  onClick={onRunDemo}
                  className="inline-flex items-center gap-2 rounded-md border border-neutral-300 bg-white px-5 py-2.5 text-sm font-medium text-neutral-700 hover:border-neutral-400 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <FlaskConical className="h-4 w-4" />
                  跑一份演示样本
                </button>
              )}
            </div>
            {!health?.llm_configured && (
              <p className="mt-3 text-xs leading-5 text-amber-700">
                提示：未检测到 {health?.llm_key_env ?? "DEEPSEEK_API_KEY"} 环境变量。上传真实文件会因 LLM 解析失败而标黄；
                想先看完整效果请用「演示样本」（内置 6 份虚拟报价，离线回放，不消耗 API）。
              </p>
            )}
          </div>

          {/* 右：运行日志 */}
          <div className="lg:col-span-2">
            <p className="text-xs font-medium text-neutral-500">运行日志</p>
            <pre className="mt-2 h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-neutral-200 bg-neutral-900 p-4 font-mono text-xs leading-5 text-neutral-200 lg:h-80">
              {log || "尚未运行。选择文件或点击「跑一份演示样本」。"}
            </pre>
          </div>
        </div>
      </div>
    </section>
  );
}
