import { useCallback, useEffect, useRef, useState } from "react";
import Hero from "../sections/Hero";
import FeatureIntro from "../sections/FeatureIntro";
import ExtractPanel from "../sections/ExtractPanel";
import ResultView from "../sections/ResultView";
import type { Health, Job } from "../types/api";

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [log, setLog] = useState("");
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  const poll = useCallback((jobId: string) => {
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = window.setInterval(async () => {
      try {
        const r = await fetch(`/api/jobs/${jobId}`);
        const j: Job = await r.json();
        setLog(j.log);
        if (j.status !== "running") {
          if (timerRef.current) window.clearInterval(timerRef.current);
          timerRef.current = null;
          setJob(j);
        }
      } catch {
        // 网络抖动时继续轮询
      }
    }, 1000);
  }, []);

  useEffect(
    () => () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
    },
    []
  );

  const startJob = useCallback(
    async (body: FormData) => {
      setJob(null);
      setLog("提交中...\n");
      const r = await fetch("/api/jobs", { method: "POST", body });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        setLog(`提交失败：${err.detail ?? r.statusText}`);
        return;
      }
      const { job_id } = await r.json();
      setLog("任务已创建，开始运行...\n");
      poll(job_id);
    },
    [poll]
  );

  const onRunFiles = useCallback(
    (files: File[]) => {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      startJob(fd);
    },
    [startJob]
  );

  const onRunDemo = useCallback(() => {
    const fd = new FormData();
    fd.append("demo", "true");
    startJob(fd);
  }, [startJob]);

  return (
    <div className="min-h-screen bg-[#FAFAF7] text-neutral-900 antialiased">
      <Hero health={health} />
      <FeatureIntro />
      <ExtractPanel
        health={health}
        running={job === null && log.length > 0 && !log.startsWith("提交失败")}
        log={log}
        onRunFiles={onRunFiles}
        onRunDemo={onRunDemo}
      />
      {job && <ResultView job={job} />}
      <footer className="border-t border-neutral-200 bg-[#FAFAF7]">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-8 text-xs text-neutral-400">
          <p>报价单提取比价工具 · 本地运行，文件不出本机</p>
          <p className="font-mono">CLI: python -m src.cli extract</p>
        </div>
      </footer>
    </div>
  );
}
