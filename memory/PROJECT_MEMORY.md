# PfinderWithAI 项目记忆

最后更新：2026-08-15

## 当前目标

第一阶段只验证简单、可控的跨系统故障链路。输入问题描述、业务标识、起始系统和时间范围或 TraceID，逐步收集 Trace、日志和代码证据，输出带调查轨迹的 `DiagnosisResult`。默认只读，不执行生产变更或自动修复。

## 已确认架构

- Python 3.12 + uv；主流程使用 LangGraph。
- 一个主调查 Agent 负责编排，Codex CodeInvestigator 是通过 `CodeAnalysisProvider` 委派的代码调查子 Agent，不拆成平级自治 Agent。
- TraceAnalyser 生成有序候选目标；候选不是已确认根因。只有 Trace 外新发现的依赖才使用 `NextHop`。
- 统一 Verifier 包含已实现的 `HypothesisVerifier` 和只保留接口的 `RuntimeVerifier`。
- 外部能力全部通过 Ports/Adapters 隔离；真实公司 API 契约等待后续开发时确认。
- 临时代码仓库由 `GitWorkspaceManager` 管策略和清理，`GitCliRepositoryAdapter` 只执行参数化 Git 命令。
- InvestigationStore 与 LangGraph Checkpointer 逻辑分离。当前只实现前者的 SQLite Adapter。
- 第一版只提供 CLI；HTTP 和前端暂缓。
- 权限平台暂缓，但保留只读、脱敏、受信任 Git 域名和模型最小上下文边界。

## 当前可运行能力

- `pfinder-ai investigate` 默认运行 Fake 场景，不访问真实公司系统或模型。
- 合成链路会定位 `system-b` 的异常 Span，收集合成日志与代码证据，通过静态 Verifier，并把结果保存到 SQLite。
- Codex SDK Adapter 已实现只读 Sandbox、拒绝权限升级、JSON Schema 输出和错误转换，但尚未通过 CLI 发起真实调用。

## 常用命令

```powershell
uv sync --dev
uv run ruff check src tests
uv run mypy src/pfinder_ai
uv run pytest tests -q
uv run pfinder-ai investigate "订单创建失败" --start-system system-a --trace-id trace-synthetic
```

## 下一步优先级

1. 整理公司 Metadata、Pfinder、日志和 LLM API 能力与字段。
2. 实现真实 Adapters 和 Contract Tests。
3. 引入 SQLite LangGraph Checkpointer 并验证中断恢复。
4. 将 UsageMonitor 统一包裹所有 Provider，并把单次调查用量写回结果。
5. 使用本地账号联调 Codex Adapter，再验证脱敏后的真实样例。

详细任务见 `docs/TODO.md`。

## 重要约定

- 新增 Python 注释和 docstring 统一使用中文。
- 每个实现模块保持小提交，功能提交使用 `feat:` 前缀。
- 示例和测试只能使用合成或彻底匿名化数据。
- 不要把 `.pfinder/`、`.env`、真实仓库缓存或生产数据提交到 Git。
