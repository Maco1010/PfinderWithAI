# PfinderWithAI

PfinderWithAI 是一个面向企业微服务场景的证据驱动根因定位 Agent。它从问题描述出发，结合 Trace、日志和代码证据，沿跨系统调用链逐层调查，并输出可追溯的结构化诊断结果。

当前仓库已经完成第一版代码骨架，并提供一条使用合成 Trace、日志和代码的可运行纵向链路。CLI 默认禁用真实模型，不会访问生产日志、内部 Git 或 Pfinder；开发者可以显式启用模型网关，仅为主图的 `ClueExtractor` 提供结构化语义提取。

## 当前已实现

- Python 3.12、uv、LangGraph、Pydantic、Typer 项目基础。
- `IncidentInput`、`Evidence`、`Hypothesis`、`DiagnosisResult` 等严格领域模型。
- Trace、日志、元数据、代码分析、仓库、存储、LLM 和 RuntimeVerifier Ports。
- LangGraph 状态、Reducer、节点、条件路由、循环和预算终止骨架。
- Trace 筛选、HypothesisVerifier、安全临时工作区和 API 用量监控服务。
- Fake Providers 与 `A -> B` 合成故障端到端链路。
- Git CLI、Codex SDK、模型网关和 SQLite InvestigationStore Adapters。
- `GatewayLLMProvider` 的强制 Tool Use、Pydantic 校验、一次格式修复、有限重试和用量记录。
- CLI、应用服务、SQLite 审计轨迹与结构化 JSON 输出。

## 尚未实现

- 公司内部 Pfinder、日志和系统元数据 Adapters。
- LangGraph SQLite Checkpointer；当前 SQLite 只保存业务调查输入、步骤和结果。
- CLI 对真实 Codex Adapter 的依赖装配与真实账号联调。
- RuntimeVerifier 实现、HTTP API、前端、权限控制和运行时 Case Memory。
- 所有 Provider 的统一 UsageMonitor 包装；当前已提供模型网关、Codex 接入点和监控组件。

这些缺口记录在 [docs/TODO.md](docs/TODO.md)。产品范围见 [docs/Requirements.md](docs/Requirements.md)，架构与流程见 [docs/Design.md](docs/Design.md) 和 [docs/InvestigationStateFlow.md](docs/InvestigationStateFlow.md)，Pfinder 元数据接口梳理见 [docs/PfinderMetadataAPI.md](docs/PfinderMetadataAPI.md)。

## 环境要求

- Python `3.12.x`
- [uv](https://docs.astral.sh/uv/)
- Git CLI（只在运行 Git Adapter 集成测试或未来真实仓库模式时需要）

## 安装

```powershell
uv sync --dev
Copy-Item .env.example .env
```

`.env.example` 只包含非敏感默认值。不要把令牌、真实内部地址、生产日志或客户数据提交到仓库。

## 运行 Fake Demo

```powershell
uv run pfinder-ai investigate "订单创建失败" `
  --start-system system-a `
  --business-key order_id=synthetic-001 `
  --time-description "最近五分钟"
```

只输出机器可读 JSON：

```powershell
uv run pfinder-ai investigate "订单创建失败" `
  --start-system system-a `
  --trace-id trace-synthetic `
  --json
```

Fake Demo 会使用合成 Trace、日志和代码，最终结果写入 `.pfinder/investigations.sqlite3`。运行时临时仓库位于 `.pfinder/workspaces`，调查结束后自动清理。

若需要确保连语义提取也不访问真实模型，请保持：

```dotenv
PFINDER_AI_LLM_PROVIDER=disabled
```

## 启用主模型网关

主图通过 `LLMProvider` Port 调用模型，当前真实实现为供应商中立的 `GatewayLLMProvider`。网关协议是配置细节，目前支持 Anthropic Messages。将以下值只写入被 Git 忽略的本地 `.env`：

```dotenv
PFINDER_AI_LLM_PROVIDER=gateway
PFINDER_AI_LLM_PROTOCOL=anthropic_messages
PFINDER_AI_LLM_BASE_URL=https://llm-gateway.example.com
PFINDER_AI_LLM_API_KEY=replace-with-local-secret
PFINDER_AI_LLM_MODEL=replace-with-model-id
PFINDER_AI_LLM_AUTH_STYLE=bearer
```

默认要求 HTTPS。本地回环地址可以使用 HTTP；受信任内网确实只能提供 HTTP 时，还需要显式设置 `PFINDER_AI_LLM_ALLOW_INSECURE_HTTP=true`。Provider 不跟随 HTTP 重定向，不记录完整 Prompt、原始响应、地址或凭证。

当前只有 `ClueExtractor` 使用主模型。Trace 排序与 HypothesisVerifier 仍使用确定性规则；CodeInvestigator 继续通过独立的 `CodeAnalysisProvider` 调用 Codex。

### 真实 ClueExtractor Smoke Test

配置好本地 `.env` 后，可以只运行 `ClueExtractor` 并查看模型解析后的 `IncidentInput`：

```powershell
uv run python tests/manual/smoke_clue_extractor.py
```

默认输入和断言全部为合成数据。测试会检查模型是否解析出预期的起始系统、Trace ID 和业务标识，并用退出码表示成功或失败；输出不包含网关地址、密钥、模型名或原始响应。传入自定义描述时，该内容会发送给模型，必须先完成脱敏：

```powershell
uv run python tests/manual/smoke_clue_extractor.py `
  "system-a 的合成订单 synthetic-002 创建失败，trace id 是 trace-synthetic-002" `
  --expect-start-system system-a `
  --expect-trace-id trace-synthetic-002
```

该脚本是需要真实凭证和网络的手工 Smoke Test，不属于默认 `pytest` 测试集，避免 CI 意外访问公司模型网关。

## 检查与测试

```powershell
uv run ruff check src tests
uv run mypy src/pfinder_ai
uv run pytest tests -q
```

测试数据全部为合成数据。本地 Git 集成测试只创建和克隆 pytest 临时目录中的仓库，不访问网络。

## 主要目录

```text
src/pfinder_ai/
|-- application/    # 对 CLI 隐藏 LangGraph 的应用用例和事件
|-- domain/         # 稳定领域模型、枚举和错误
|-- graph/          # State、节点、路由、预算策略和图构建器
|-- ports/          # 外部能力的 Protocol 契约
|-- adapters/       # Fake、模型网关、Codex、Git CLI 和 SQLite 实现
|-- services/       # Trace 分析、验证和工作区生命周期
|-- monitoring/     # 非敏感 API 用量监控
`-- strategies/     # 随版本发布的固定调查策略

memory/             # 跨设备开发上下文，不是运行时 Case Memory
tests/              # unit、contract 和 integration 测试
```

## 安全边界

- 默认只读诊断，不触发生产变更或自动修复。
- HTTP Git URL 禁止内嵌用户名、令牌或密码；仓库必须通过受信任域名校验。
- Codex Adapter 使用只读 Sandbox、拒绝权限升级并要求结构化输出。
- 模型网关 Adapter 使用强制 Tool Use 和 Pydantic 校验，凭证仅从本地环境读取。
- 日志和代码证据进入状态前检查来源类型和脱敏标记。
- 模型推断不会被表述为已确认的运行时事实；RuntimeVerifier 未执行时会明确披露。

## 跨设备开发记忆

切换设备或新会话时，先阅读 [memory/PROJECT_MEMORY.md](memory/PROJECT_MEMORY.md)。该目录只保存可提交的项目上下文、决策和接力说明，不得保存密钥、真实日志、内部地址或客户数据。
