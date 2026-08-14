import { FileSpreadsheet, FileText, FileImage, ScanText, FileType } from "lucide-react";

const FORMATS = [
  { icon: FileSpreadsheet, name: "Excel", desc: ".xlsx / .xls 直接读取单元格" },
  { icon: FileText, name: "PDF 数字版", desc: "内嵌文本层直接抽取" },
  { icon: ScanText, name: "PDF 扫描件", desc: "300 DPI 渲染后 OCR 识别" },
  { icon: FileImage, name: "图片", desc: ".png / .jpg 全页 OCR" },
  { icon: FileType, name: "文本", desc: ".txt / .csv 自动识别编码" },
];

const STAGES = [
  { no: "01", name: "格式分拣", desc: "识别五类格式，不支持的直接拒收" },
  { no: "02", name: "内容提取", desc: "文本层 / OCR 拿到原文，低置信行记录在案" },
  { no: "03", name: "结构化解析", desc: "LLM 只产出原文摘录 + 置信度，不直接出数字" },
  { no: "04", name: "规则校验", desc: "数量单价由规则解析，V1~V7 七条校验逐一过" },
  { no: "05", name: "比价分析", desc: "跨供应商对齐物料，算均价 / 偏离 / 缺报" },
  { no: "06", name: "导出 Excel", desc: "比价总表 + 明细 + 统计与异常，五色标色" },
];

const LEGEND = [
  { color: "#C6EFCE", label: "绿 · 该物料最低价" },
  { color: "#FFC7CE", label: "红 · 高于均价 15% 以上" },
  { color: "#FFE0B2", label: "橙 · 交期最长且超中位数 2 倍" },
  { color: "#FFF3CD", label: "黄 · 低置信 / 校验未过 / 待确认（最高优先级）" },
  { color: "#D9D9D9", label: "灰 · 该供应商缺报此项" },
];

export default function FeatureIntro() {
  return (
    <section id="intro" className="border-t border-neutral-200 bg-white">
      <div className="mx-auto max-w-6xl px-6 py-16">
        <p className="text-xs font-semibold tracking-[0.2em] text-orange-700">它能做什么</p>
        <h2 className="mt-2 text-2xl font-bold tracking-tight text-neutral-900">
          把一堆格式各异的报价单，变成一张可以决策的比价表
        </h2>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-neutral-600">
          采购收到的报价单什么格式都有：Excel、PDF、扫描件、照片、微信里复制出来的文本。
          这个工具把它们统一解析成结构化报价行，跨供应商对齐同一物料，标出谁最低、谁偏高、谁没报，
          最后导出一张带标色的比价 Excel。原则只有一条：
          <span className="font-semibold text-neutral-900">允许出错，但不允许错了不告诉你</span>——所有不确定的地方都会标黄并给出原文片段供复核。
        </p>

        {/* 支持格式 */}
        <div className="mt-10 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-neutral-200 bg-neutral-200 sm:grid-cols-5">
          {FORMATS.map((f) => (
            <div key={f.name} className="bg-white p-5">
              <f.icon className="h-5 w-5 text-neutral-700" strokeWidth={1.5} />
              <p className="mt-3 text-sm font-semibold text-neutral-900">{f.name}</p>
              <p className="mt-1 text-xs leading-5 text-neutral-500">{f.desc}</p>
            </div>
          ))}
        </div>

        {/* 六阶段流水线 */}
        <p className="mt-14 text-xs font-semibold tracking-[0.2em] text-orange-700">怎么做到的</p>
        <h3 className="mt-2 text-xl font-bold tracking-tight text-neutral-900">六阶段流水线，每一步都可复核</h3>
        <ol className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {STAGES.map((s) => (
            <li key={s.no} className="border-t-2 border-neutral-900 pt-4">
              <p className="font-mono text-xs text-neutral-400">{s.no}</p>
              <p className="mt-1 text-sm font-semibold text-neutral-900">{s.name}</p>
              <p className="mt-1 text-xs leading-5 text-neutral-500">{s.desc}</p>
            </li>
          ))}
        </ol>

        {/* 五色图例 */}
        <p className="mt-14 text-xs font-semibold tracking-[0.2em] text-orange-700">结果怎么读</p>
        <h3 className="mt-2 text-xl font-bold tracking-tight text-neutral-900">五色标色，一眼看清风险与机会</h3>
        <ul className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {LEGEND.map((l) => (
            <li key={l.color} className="flex items-start gap-3">
              <span
                className="mt-0.5 inline-block h-4 w-4 shrink-0 rounded-sm border border-black/10"
                style={{ backgroundColor: l.color }}
              />
              <span className="text-xs leading-5 text-neutral-600">{l.label}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
