# 后续待办

本文只记录第一版骨架之后仍未完成的工作，不把探索项表述为既定方案。

## P0：真实能力接入前必须完成

- 明确并实现公司 Metadata API Adapter：系统名、Git 地址、线上版本、日志源和 Pfinder 标识。
- 明确并实现 Pfinder/Trace API Adapter：查询条件、分页、来源链接、错误分类和限流。
- 明确并实现日志 API Adapter：时间范围、业务 Key、TraceID、分页、裁剪和脱敏责任。
- 确认 LLMProvider 的供应商、认证和结构化输出契约，并实现真实 Adapter。
- 为 LangGraph 引入兼容版本的 SQLite Checkpointer，验证中断恢复；不得与 InvestigationStore 混用职责。
- 用真实但彻底脱敏的样例验证 `A -> B -> C/D` 链路，并补齐 Contract Tests。

## P0：可观测性和执行边界

- 使用统一装饰器或代理为 Metadata、Trace、日志、Git、Codex 和 LLM Provider 接入 UsageMonitor。
- 将每次调查的 UsageRecord 注入 LangGraph State 和最终 DiagnosisResult，而不是只保留进程级快照。
- 根据真实 API 行为确定超时、有限重试、时间、Token 和成本预算默认值。
- 验证 Checkpointer 恢复后步骤 ID、Provider 重试和存储写入仍保持幂等。

## P1：真实代码调查

- 在本地测试账号下联调 Codex SDK 登录、模型选择、只读 Sandbox 和结构化输出。
- 根据真实仓库规模验证浅克隆、精确 commit、认证 helper、超时和错误脱敏。
- 为 CodeInvestigator 增加部分结果、预算终止、补充日志请求和新依赖发现的评测集。

## 暂缓项

- RuntimeVerifier 真实实现。
- HTTP API、前端、用户会话和多租户。
- 权限控制平台集成；当前仅保留只读和本地安全边界。
- CaseMemoryProvider 的向量检索或历史故障复用。
- RLM、Code Graph、RSI 或运行时策略自修改。
