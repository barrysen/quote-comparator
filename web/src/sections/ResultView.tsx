import { Download, TriangleAlert } from "lucide-react";
import type { GroupEntry, ItemGroup, Job } from "../types/api";

const PRICE_DEVIATION_THRESHOLD = 0.15; // 与 config/settings.yml compare.price_deviation_threshold 一致

function fmtPrice(v: number | null): string {
  if (v == null) return "—";
  return v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** 与导出 Excel 的五色标色规则对齐（黄优先，覆盖其他颜色） */
function cellColor(group: ItemGroup, entry: GroupEntry | undefined, missing: boolean): string {
  if (missing) return "#D9D9D9";
  if (!entry) return "transparent";
  const line = entry.line;
  if (group.review || line.confidence === "low" || line.flags.length > 0) return "#FFF3CD";
  const dev = group.deviations[entry.supplier_name];
  if (dev != null && dev > PRICE_DEVIATION_THRESHOLD) return "#FFC7CE";
  if (group.min_price != null && line.unit_price === group.min_price && group.entries.length > 1)
    return "#C6EFCE";
  return "transparent";
}

function leadTimeAlert(group: ItemGroup, entry: GroupEntry): boolean {
  const d = entry.line.lead_time_days;
  return (
    d != null &&
    group.max_lead_days != null &&
    group.median_lead_days != null &&
    d === group.max_lead_days &&
    group.max_lead_days > group.median_lead_days * 2
  );
}

export default function ResultView({ job }: { job: Job }) {
  const result = job.result;
  if (job.status === "error") {
    return (
      <section className="border-t border-neutral-200 bg-white">
        <div className="mx-auto max-w-6xl px-6 py-16">
          <div className="rounded-lg border border-red-200 bg-red-50 p-6">
            <p className="flex items-center gap-2 text-sm font-semibold text-red-800">
              <TriangleAlert className="h-4 w-4" /> 任务失败
            </p>
            <p className="mt-2 text-sm text-red-700">{job.error}</p>
          </div>
        </div>
      </section>
    );
  }
  if (job.status !== "done" || !result) return null;

  const { comparison } = result;
  const s = job.summary;
  const base = `/api/jobs/${job.job_id}/files`;

  return (
    <section className="border-t border-neutral-200 bg-white">
      <div className="mx-auto max-w-6xl px-6 py-16">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold tracking-[0.2em] text-orange-700">结果</p>
            <h2 className="mt-2 text-2xl font-bold tracking-tight text-neutral-900">
              {job.demo ? "演示样本比价结果" : "比价结果"}
            </h2>
          </div>
          <div className="flex gap-2">
            <a href={`${base}/xlsx`} className="inline-flex items-center gap-1.5 rounded-md bg-neutral-900 px-4 py-2 text-xs font-medium text-white hover:bg-neutral-700">
              <Download className="h-3.5 w-3.5" /> 比价 Excel
            </a>
            <a href={`${base}/report`} className="inline-flex items-center gap-1.5 rounded-md border border-neutral-300 px-4 py-2 text-xs font-medium text-neutral-700 hover:border-neutral-400">
              <Download className="h-3.5 w-3.5" /> 文本报告
            </a>
            <a href={`${base}/json`} className="inline-flex items-center gap-1.5 rounded-md border border-neutral-300 px-4 py-2 text-xs font-medium text-neutral-700 hover:border-neutral-400">
              <Download className="h-3.5 w-3.5" /> JSON
            </a>
          </div>
        </div>

        {/* 汇总 */}
        {s && (
          <div className="mt-8 grid grid-cols-3 gap-px overflow-hidden rounded-lg border border-neutral-200 bg-neutral-200 sm:grid-cols-6">
            {[
              ["供应商", s.suppliers],
              ["报价行", s.quote_lines],
              ["物料组", s.groups],
              ["缺报", s.missing],
              ["校验发现", s.findings],
              ["失败文件", s.failed_files],
            ].map(([label, v]) => (
              <div key={label} className="bg-white px-4 py-4">
                <p className="font-mono text-2xl font-semibold text-neutral-900">{v}</p>
                <p className="mt-1 text-xs text-neutral-500">{label}</p>
              </div>
            ))}
          </div>
        )}

        {/* 比价矩阵 */}
        <div className="mt-10 overflow-x-auto rounded-lg border border-neutral-200">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="bg-neutral-50 text-left text-xs text-neutral-500">
                <th className="px-4 py-3 font-medium">物料 / 规格</th>
                {comparison.suppliers.map((sp) => (
                  <th key={sp} className="px-4 py-3 font-medium">{sp}</th>
                ))}
                <th className="px-4 py-3 font-medium">均价</th>
              </tr>
            </thead>
            <tbody>
              {comparison.groups.map((g) => (
                <tr key={g.key} className="border-t border-neutral-100">
                  <td className="px-4 py-3 align-top">
                    <p className="font-medium text-neutral-900">{g.item_name}</p>
                    {g.spec && <p className="mt-0.5 font-mono text-xs text-neutral-400">{g.spec}</p>}
                    {g.review && <p className="mt-1 text-xs text-amber-700">待确认匹配</p>}
                  </td>
                  {comparison.suppliers.map((sp) => {
                    const entry = g.entries.find((e) => e.supplier_name === sp);
                    const missing = comparison.missing.some(
                      (m) => m.item === g.item_name && m.supplier === sp
                    );
                    const bg = cellColor(g, entry, missing);
                    return (
                      <td key={sp} className="px-4 py-3 align-top" style={{ backgroundColor: bg }}>
                        {entry ? (
                          <>
                            <p className="font-mono font-medium text-neutral-900">
                              ¥{fmtPrice(entry.line.unit_price)}
                            </p>
                            <p className="mt-0.5 text-xs text-neutral-500">
                              {entry.line.quantity ?? "—"} {entry.line.unit}
                              {entry.line.lead_time_days != null && (
                                <span
                                  className="ml-1 rounded-sm px-1"
                                  style={leadTimeAlert(g, entry) ? { backgroundColor: "#FFE0B2" } : undefined}
                                >
                                  {entry.line.lead_time_days}天
                                </span>
                              )}
                            </p>
                            {entry.line.flags.length > 0 && (
                              <p className="mt-0.5 font-mono text-xs text-amber-700">
                                {entry.line.flags.join(" ")}
                              </p>
                            )}
                          </>
                        ) : (
                          <span className="text-xs text-neutral-400">{missing ? "缺报" : "—"}</span>
                        )}
                      </td>
                    );
                  })}
                  <td className="px-4 py-3 align-top font-mono text-neutral-600">
                    {g.avg_price != null ? `¥${fmtPrice(g.avg_price)}` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* 校验发现 */}
        {result.findings.length > 0 && (
          <div className="mt-10">
            <h3 className="text-sm font-semibold text-neutral-900">
              校验发现（{result.findings.length}）——这些位置建议人工复核
            </h3>
            <ul className="mt-3 divide-y divide-neutral-100 rounded-lg border border-neutral-200">
              {result.findings.map((f, i) => (
                <li key={i} className="flex items-baseline gap-3 px-4 py-2.5 text-sm">
                  <span className="shrink-0 rounded-sm bg-amber-100 px-1.5 py-0.5 font-mono text-xs font-semibold text-amber-800">
                    {f.rule}
                  </span>
                  <span className="shrink-0 font-mono text-xs text-neutral-400">{f.target}</span>
                  <span className="text-neutral-700">{f.message}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* 失败文件 */}
        {result.failed_files.length > 0 && (
          <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4">
            <p className="text-sm font-semibold text-red-800">未能解析的文件</p>
            <ul className="mt-2 space-y-1 text-sm text-red-700">
              {result.failed_files.map((f, i) => (
                <li key={i} className="font-mono text-xs">{f.file} — {f.reason}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}
