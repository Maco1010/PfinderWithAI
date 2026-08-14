"""调查流程使用的、与供应商无关的领域类型。

本包不得导入 LangGraph、Codex、数据库驱动或公司内部 SDK，以确保所有
Provider Adapter 都能够被替换和独立测试。
"""
