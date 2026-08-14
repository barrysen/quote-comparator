"""阶段五：比价分析（M3）—— 跨文件对齐物料，产出比价矩阵。

流程（设计方案 §3.5）：
1. 同供应商多文件合并（文件名含"补充/更正/更新"的视为后报价，覆盖同物料旧值）；
2. 第一遍（规则）：归一化后按 "名称+规格" 精确匹配分组；
3. 第二遍（LLM 兜底）：孤立组两两候选 → LLM 判定是否同一物料。
   **保守策略：置信度 low 一律不合并**，两组相邻放置并标黄提示人工确认；
4. 每组统计：报价家数、最低/最高价、均价、偏离均价百分比、最短/最长交期；
5. 缺报检测：某物料 ≥2 家报价但某供应商未报 → 记缺报。
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from statistics import mean, median

from src.llm.client import LLMClient, LLMError
from src.models import Comparison, GroupEntry, ItemGroup, SupplierQuote

MATCH_SCHEMA_NAME = "item_match"
MATCH_SYSTEM = "你是物料对齐判定助手。你只输出 JSON，不输出任何其他文字。"
MATCH_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "same": {"type": "boolean"},
                    "confidence": {"type": "string", "enum": ["high", "low"]},
                    "reason": {"type": "string"},
                },
                "required": ["id", "same", "confidence", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

# 文件名含这些词视为对同供应商旧报价的覆盖（后报价优先）
SUPPLEMENT_HINTS = ("补充", "更正", "更新")


# ---------- 归一化与对齐 ----------

def normalize_text(s: str) -> str:
    """全半角统一、转小写、×/* 统一为 x、去空白。"""
    s = unicodedata.normalize("NFKC", s or "")
    s = s.lower().replace("×", "x").replace("*", "x").replace("＊", "x")
    return re.sub(r"\s+", "", s)


def item_key(name: str, spec: str) -> str:
    return f"{normalize_text(name)}|{normalize_text(spec)}"


def display_text(name: str, spec: str) -> str:
    return f"{name} {spec}".strip()


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", normalize_text(s)))


_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


def _cjk_overlap(a: str, b: str, n: int = 3) -> bool:
    """两条描述共享长度 ≥n 的中文子串（如"深沟球轴承"），容忍规格区 OCR 噪音。"""
    ra = "".join(_CJK_RE.findall(normalize_text(a)))
    rb = "".join(_CJK_RE.findall(normalize_text(b)))
    if len(ra) < n or len(rb) < n:
        return False
    short, long_ = sorted((ra, rb), key=len)
    return any(short[i : i + n] in long_ for i in range(len(short) - n + 1))


def _prefilter(text_a: str, text_b: str) -> bool:
    """候选对粗筛（控制 LLM 判定规模）：名称互相包含 / 共享含数字 token / 共享中文子串。"""
    na, nb = normalize_text(text_a), normalize_text(text_b)
    if len(na) >= 2 and na in nb:
        return True
    if len(nb) >= 2 and nb in na:
        return True
    shared = _tokens(text_a) & _tokens(text_b)
    if any(any(ch.isdigit() for ch in t) for t in shared):
        return True
    return _cjk_overlap(text_a, text_b)


# ---------- 同供应商多文件合并 ----------

def _file_rank(source_file: str) -> tuple[int, str]:
    is_supplement = any(h in source_file for h in SUPPLEMENT_HINTS)
    return (1 if is_supplement else 0, source_file)


def merge_suppliers(quotes: list[SupplierQuote]) -> tuple[dict[str, dict[str, GroupEntry]], list[str], list[str]]:
    """{supplier: {item_key: GroupEntry}}；同供应商同物料后报价覆盖先报价。"""
    ordered = sorted(quotes, key=lambda q: _file_rank(q.source_file))
    suppliers: list[str] = []
    supplier_items: dict[str, dict[str, GroupEntry]] = {}
    notes: list[str] = []
    for quote in ordered:
        if not quote.lines:
            continue  # 降级/失败文件（0 条报价行）不进入比价矩阵
        if quote.supplier_name not in supplier_items:
            supplier_items[quote.supplier_name] = {}
            suppliers.append(quote.supplier_name)
        items = supplier_items[quote.supplier_name]
        for line in quote.lines:
            key = item_key(line.item_name, line.spec)
            if key in items:
                notes.append(
                    f"{quote.supplier_name}: {line.item_name} 以 {quote.source_file} 覆盖 {items[key].source_file}"
                )
            items[key] = GroupEntry(
                supplier_name=quote.supplier_name, source_file=quote.source_file, line=line
            )
    return supplier_items, suppliers, notes


def first_pass_groups(supplier_items: dict[str, dict[str, GroupEntry]]) -> list[ItemGroup]:
    """规则分组：归一化 "名称+规格" 精确匹配。"""
    groups: dict[str, ItemGroup] = {}
    for supplier, items in supplier_items.items():
        for key, entry in items.items():
            if key not in groups:
                groups[key] = ItemGroup(
                    key=key, item_name=entry.line.item_name, spec=entry.line.spec
                )
            groups[key].entries.append(entry)
    return list(groups.values())


# ---------- LLM 兜底匹配 ----------

def build_match_request(
    quotes: list[SupplierQuote], config: dict
) -> tuple[str, list[dict], dict[str, ItemGroup], list[ItemGroup]] | None:
    """构造物料对齐 LLM 请求。返回 (user_prompt, pairs, key→group, groups)。

    拆成独立函数是为了让 replay 录制脚本复用同一请求，保证哈希一致。
    注意：返回的 groups 与 by_key 指向同一批对象，run() 必须直接使用，
    不得另行重建（否则合并会改在副本上）。
    """
    supplier_items, _, _ = merge_suppliers(quotes)
    groups = first_pass_groups(supplier_items)
    by_key = {g.key: g for g in groups}
    orphans = [g for g in groups if len(g.entries) == 1]

    pairs: list[dict] = []
    seen: set[frozenset] = set()
    for o in orphans:
        o_text = display_text(o.item_name, o.spec)
        o_supplier = o.entries[0].supplier_name
        for g in groups:
            if g.key == o.key:
                continue
            if any(e.supplier_name == o_supplier for e in g.entries):
                continue  # 同供应商不互配
            g_text = display_text(g.item_name, g.spec)
            if not _prefilter(o_text, g_text):
                continue
            dedup = frozenset((o.key, g.key))
            if dedup in seen:
                continue
            seen.add(dedup)
            pairs.append({"id": str(len(pairs)), "a": o_text, "b": g_text,
                          "_ka": o.key, "_kb": g.key})
    if not pairs:
        return None
    template = Path(config["prompts"]["match_items"]).read_text(encoding="utf-8")
    payload = {"pairs": [{"id": p["id"], "a": p["a"], "b": p["b"]} for p in pairs]}
    user = template.replace("{{pairs_json}}", json.dumps(payload, ensure_ascii=False, indent=2))
    return user, pairs, by_key, groups


def _apply_match_results(
    groups: list[ItemGroup],
    by_key: dict[str, ItemGroup],
    pairs: list[dict],
    results: list[dict],
    notes: list[str],
) -> None:
    """应用 LLM 判定：high 合并；low 不合并、标 review 相邻放置。"""
    pair_by_id = {p["id"]: p for p in pairs}
    merged_away: set[str] = set()
    for res in results:
        pair = pair_by_id.get(str(res.get("id")))
        if not pair or not res.get("same"):
            continue
        ga, gb = by_key[pair["_ka"]], by_key[pair["_kb"]]
        if ga.key in merged_away or gb.key in merged_away:
            continue
        if res.get("confidence") == "high":
            gb.entries.extend(ga.entries)
            gb.notes.append(
                f"LLM 合并: '{display_text(ga.item_name, ga.spec)}' 并入本组（{res.get('reason', '')}）"
            )
            merged_away.add(ga.key)
            groups.remove(ga)
            notes.append(
                f"物料合并: '{display_text(ga.item_name, ga.spec)}' ≈ '{display_text(gb.item_name, gb.spec)}'"
            )
        else:
            # 保守策略：低置信不合并，标黄相邻放置待人工
            ga.review = gb.review = True
            ga.notes.append(f"疑似与 '{display_text(gb.item_name, gb.spec)}' 同物料（低置信，未合并，请人工确认）")
            gb.notes.append(f"疑似与 '{display_text(ga.item_name, ga.spec)}' 同物料（低置信，未合并，请人工确认）")
            notes.append(
                f"待确认匹配: '{display_text(ga.item_name, ga.spec)}' ? '{display_text(gb.item_name, gb.spec)}'"
            )
            _place_adjacent(groups, ga, gb)


def _place_adjacent(groups: list[ItemGroup], ga: ItemGroup, gb: ItemGroup) -> None:
    if ga in groups and gb in groups:
        groups.remove(gb)
        groups.insert(groups.index(ga) + 1, gb)


# ---------- 统计与缺报 ----------

def _dedupe_within_group(group: ItemGroup, notes: list[str]) -> None:
    """LLM 合并后，同供应商在组内仍可能有多条（规格写法差异绕过精确去重）：
    保留后报价（文件名含 补充/更正/更新 者优先），并记录。"""
    best: dict[str, GroupEntry] = {}
    for e in group.entries:
        cur = best.get(e.supplier_name)
        if cur is None or _file_rank(e.source_file) >= _file_rank(cur.source_file):
            if cur is not None:
                notes.append(
                    f"{e.supplier_name}: {group.item_name} 以 {e.source_file} 覆盖 {cur.source_file}"
                )
            best[e.supplier_name] = e
        else:
            notes.append(
                f"{e.supplier_name}: {group.item_name} 以 {cur.source_file} 覆盖 {e.source_file}"
            )
    group.entries = list(best.values())


def _fill_stats(group: ItemGroup) -> None:
    prices = {
        e.supplier_name: e.line.unit_price
        for e in group.entries
        if e.line.unit_price is not None
    }
    if prices:
        group.min_price = min(prices.values())
        group.max_price = max(prices.values())
        group.avg_price = mean(prices.values())
        group.deviations = {
            s: (p - group.avg_price) / group.avg_price for s, p in prices.items()
        }
    leads = [e.line.lead_time_days for e in group.entries if e.line.lead_time_days is not None]
    if leads:
        group.min_lead_days = min(leads)
        group.max_lead_days = max(leads)
        group.median_lead_days = median(leads)


def _detect_missing(groups: list[ItemGroup], suppliers: list[str]) -> list[dict]:
    missing: list[dict] = []
    for g in groups:
        if len(g.entries) < 2:
            continue  # 只有 1 家报价不构成"缺报"
        quoted = {e.supplier_name for e in g.entries}
        for s in suppliers:
            if s not in quoted:
                missing.append({"item": display_text(g.item_name, g.spec), "supplier": s})
    return missing


# ---------- 入口 ----------

def run(input: dict, config: dict, llm: LLMClient | None) -> Comparison:
    quotes = [SupplierQuote.model_validate(q) for q in input.get("quotes", [])]
    supplier_items, suppliers, notes = merge_suppliers(quotes)

    req = build_match_request(quotes, config) if llm is not None else None
    if req is not None:
        user, pairs, by_key, groups = req
    else:
        groups = first_pass_groups(supplier_items)
        pairs, by_key = [], {g.key: g for g in groups}
    if req is not None:
        try:
            data = llm.complete_json(
                system=MATCH_SYSTEM, user=user,
                schema_name=MATCH_SCHEMA_NAME, schema=MATCH_SCHEMA,
            )
            _apply_match_results(groups, by_key, pairs, data.get("results") or [], notes)
        except LLMError as e:
            # 保守降级：不做智能合并，孤立组标 review 提示人工
            notes.append(f"物料对齐 LLM 失败，未做智能合并: {e}")
            for p in pairs:
                for k in (p["_ka"], p["_kb"]):
                    g = by_key[k]
                    if g in groups:
                        g.review = True
                        g.notes.append("物料对齐 LLM 失败，本组未经智能匹配，请人工确认")

    for g in groups:
        _dedupe_within_group(g, notes)
        _fill_stats(g)
    missing = _detect_missing(groups, suppliers)
    return Comparison(suppliers=suppliers, groups=groups, missing=missing, notes=notes)
