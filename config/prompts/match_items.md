# 任务（M3 物料对齐兜底）

判断两条来自不同供应商报价单的物料描述是否为**同一物料**。

# 输入

```json
{"pairs": [{"id": "1", "a": "内六角螺钉 M8×20", "b": "M8*20 内六角螺丝"}]}
```

# 判定规则

1. 规格型号一致（允许 ×/* 、空格、大小写、全半角差异）且名称指向同一类物料 → same=true。
2. 规格缺失或明显不同 → same=false。
3. **拿不准一律 same=false 或 confidence=low** —— 宁可不合并，不可错误合并。

# 输出 JSON

```json
{"results": [{"id": "1", "same": true, "confidence": "high", "reason": "规格 M8×20 与 M8*20 等价，螺钉/螺丝同义"}]}
```

# 待判定对

{{pairs_json}}
