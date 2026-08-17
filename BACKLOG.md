# BACKLOG

> 设计方案 §1.2 明确的非目标，开发过程中遇到一律记录在此，**不在 v1.0 实现**。

- 供应商主数据管理、历史价格数据库（v2.0）→ [Issue #1](https://github.com/barrysen/quote-comparator/issues/1)
- 自动发询价邮件、对接 ERP / SRM 系统 → [Issue #2](https://github.com/barrysen/quote-comparator/issues/2)
- 税率 / 汇率 / 运费的总价精算（v2.5，v1.0 仅按报价原文提取 + 数量×单价≈金额合理性检查）→ [Issue #3](https://github.com/barrysen/quote-comparator/issues/3)
- 合同、订单等其他单据类型（v1.0 仅报价单）→ [Issue #4](https://github.com/barrysen/quote-comparator/issues/4)

## 已提前落地

- ~~Web 平台（v3.0，v1.0 为命令行工具）~~ —— 应用户需求提前实现：本地 Web UI
  （`web/` + `src/web/app.py`），含功能介绍页、上传提取、比价矩阵预览与产物下载；
  仍为单机本地形态，多用户/在线部署属后续范畴。
