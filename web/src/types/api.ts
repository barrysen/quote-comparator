// 与后端 src/models.py / src/web/app.py 对应的类型

export interface QuoteLine {
  item_name: string;
  spec: string;
  quantity: number | null;
  unit: string;
  unit_price: number | null;
  lead_time_days: number | null;
  payment_terms: string;
  remark: string;
  confidence: "high" | "low";
  source_snippet: string;
  flags: string[];
}

export interface SupplierQuote {
  source_file: string;
  kind: string;
  supplier_name: string;
  lines: QuoteLine[];
  warnings: string[];
}

export interface Finding {
  target: string;
  rule: string;
  message: string;
}

export interface GroupEntry {
  supplier_name: string;
  source_file: string;
  line: QuoteLine;
}

export interface ItemGroup {
  key: string;
  item_name: string;
  spec: string;
  entries: GroupEntry[];
  review: boolean;
  notes: string[];
  avg_price: number | null;
  min_price: number | null;
  max_price: number | null;
  deviations: Record<string, number>;
  min_lead_days: number | null;
  max_lead_days: number | null;
  median_lead_days: number | null;
}

export interface Comparison {
  suppliers: string[];
  groups: ItemGroup[];
  missing: { item: string; supplier: string }[];
  notes: string[];
}

export interface ExtractResult {
  quotes: SupplierQuote[];
  findings: Finding[];
  failed_files: { file: string; reason: string }[];
  comparison: Comparison;
}

export interface JobSummary {
  suppliers: number;
  quote_lines: number;
  groups: number;
  missing: number;
  findings: number;
  failed_files: number;
}

export interface Job {
  job_id: string;
  status: "running" | "done" | "error";
  log: string;
  demo: boolean;
  summary?: JobSummary;
  result?: ExtractResult;
  error?: string;
}

export interface Health {
  ok: boolean;
  llm_configured: boolean;
  llm_key_env: string;
  demo_available: boolean;
}

export interface ModelProfile {
  name: string;
  label: string;
  base_url: string;
  model: string;
  api_key_env: string;
  key_configured: boolean;
}

export interface ModelsResponse {
  active: string;
  profiles: ModelProfile[];
}
