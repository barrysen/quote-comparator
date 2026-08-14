import { ArrowDown, CircleCheck, CircleAlert } from "lucide-react";
import type { Health } from "../types/api";

export default function Hero({ health }: { health: Health | null }) {
  return (
    <header className="bg-[#FAFAF7]">
      <div className="mx-auto max-w-6xl px-6 pb-16 pt-14">
        <div className="flex items-center justify-between">
          <p className="font-mono text-xs tracking-[0.25em] text-neutral-500">QUOTE COMPARATOR</p>
          {health && (
            <p className="flex items-center gap-1.5 text-xs text-neutral-500">
              {health.llm_configured ? (
                <>
                  <CircleCheck className="h-3.5 w-3.5 text-emerald-600" />
                  LLM 已配置（{health.llm_key_env}）
                </>
              ) : (
                <>
                  <CircleAlert className="h-3.5 w-3.5 text-amber-600" />
                  未配置 {health.llm_key_env}，可在 config/models.yml 填 api_key，或先用演示模式体验
                </>
              )}
            </p>
          )}
        </div>
        <h1 className="mt-10 max-w-3xl text-4xl font-bold leading-[1.15] tracking-tight text-neutral-900 sm:text-5xl">
          报价单扔进来，
          <br />
          比价表拿出去。
        </h1>
        <p className="mt-6 max-w-xl text-base leading-7 text-neutral-600">
          批量解析 Excel / PDF / 扫描件 / 图片 / 文本报价单，
          自动对齐同一物料的多家报价，标出最低价、偏高价、缺报和数据疑点，
          导出一张带五色标色的比价 Excel。
        </p>
        <div className="mt-10 flex items-center gap-4">
          <a
            href="#extract"
            className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-neutral-700"
          >
            开始提取
            <ArrowDown className="h-4 w-4" />
          </a>
          <a href="#intro" className="text-sm font-medium text-neutral-600 underline-offset-4 hover:underline">
            了解工作原理
          </a>
        </div>
      </div>
    </header>
  );
}
