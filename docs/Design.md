# 设计文档

第一版端到端范围与通过标准见 [第一版 Demo 验收方案](./DemoAcceptance.md)，LangGraph 调查节点和状态流转见 [调查状态流转设计](./InvestigationStateFlow.md)。

## 技术选型

1. 项目的流程编排使用 LangGraph。代码分析能力在 Demo 阶段优先使用 Python Codex SDK，并通过本地 ChatGPT/Codex 登录使用现有订阅额度，不要求单独购买 OpenAI API。核心流程通过 `CodeAnalysisProvider` 接口调用代码分析能力，避免直接依赖 Codex SDK；OpenHands 等方案作为后续候选实现，不在第一版同时接入。该认证方式仅用于本地单用户 Demo，生产或多人环境需要改用企业级服务身份或独立 API，并补充权限隔离、用量控制和审计能力。

### 模型接入边界

主 LangGraph 通过统一的 `LLMProvider` 调用通用语言模型，用于 ClueExtractor 的语义提取、TraceAnalyser 的歧义处理、HypothesisVerifier 的证据综合等需要模型推理的节点。具体模型、服务地址、认证、超时和重试策略通过配置提供，第一版可以接入公司内部 LLM API；若内部能力暂不可用，也可以使用独立计费的 OpenAI API 实现。

LLMProvider 与用于代码调查的 `CodeAnalysisProvider` 相互独立。Codex SDK 只负责 CodeInvestigator 的代码库调查，不作为主流程的通用 LLM 接口。所有 LLMProvider 输出进入业务流程前必须经过结构化解析和校验；解析失败、字段缺失或服务不可用时返回可观察的错误，由主流程决定重试、降级或终止，不能静默补全。

### API 用量监控边界

第一版不实现细粒度权限判断和人工审批流程，默认运行环境已经为当前身份配置所需的数据源和代码仓库访问权限，所有调查能力仍保持只读。权限申请、跨系统审批和按数据敏感等级控制作为后续企业化能力，不纳入 Demo。

第一版实现统一的 `UsageMonitor`，按调查任务和调查步骤记录 LLMProvider、CodeAnalysisProvider、Pfinder、日志 API 和仓库操作的调用次数、耗时、成功或失败状态及重试次数。对于能够返回用量信息的模型调用，同时记录输入 Token、输出 Token 和供应商返回的其他用量指标；成本估算使用可配置的计费信息，无法获取精确用量或价格时必须标记为未知，不能猜测。

UsageMonitor 只保存用量元数据，不记录完整 Prompt、原始日志、代码内容、访问令牌或其他敏感数据。主调查 Agent 可以根据已确认的时间和 Token/成本预算读取累计用量并终止调查；第一版不实现自动充值、账单管理或供应商配额修改。

### Agent 编排边界

第一版使用 LangGraph 构建一个主调查 Agent，不拆分为多个平级自治 Agent。主 Agent 负责流程编排、调查状态传递、条件分支、重试和终止控制，不直接实现 Pfinder 查询、日志检索或代码分析能力。代码调查由主 Agent 通过 `CodeAnalysisProvider` 委派给 Codex CodeInvestigator 子 Agent；该子 Agent 可以在限定的代码库、入口和预算内自主搜索、阅读和追踪代码，并返回结构化证据。

Pfinder、日志、代码分析等外部能力通过独立 Provider 接口接入，领域逻辑只依赖接口及结构化结果。第一版的主流程为：

`提取线索 -> 定位 Trace -> 生成候选目标队列 -> 查询目标日志与代码 -> 判断证据是否充分 -> 选择后续目标或输出结果`

调查流程允许根据证据不足、Trace 中尚未调查的候选目标和调查中新发现的依赖进行循环，也可以针对不同异常 Span 或系统多次调用 CodeInvestigator。只有 Trace 外的新系统、异步调用或外部依赖才登记为 NextHop；普通候选切换不使用该概念。流程必须设置最大调查深度、已访问系统集合、时间预算和 Token/成本预算。满足任一终止条件时，输出当前最佳假设及未决问题。Memory 在第一版只保留接口，不参与流程决策。待单链路 Demo 验证后，再评估是否需要增加其他平级或专用 Agent。

### Trace 分析边界

`TraceFinder` 负责根据 TraceID，或起始系统、业务 Key 和时间范围，从 Pfinder 获取一个或多个候选 Trace，不负责判断根因。`TraceAnalyser` 负责使用确定性逻辑对候选 Trace 进行过滤和排序，识别异常、超时、高耗时、错误传播节点及关键上下游关系，并生成按优先级排列的候选调查目标队列；只有在链路存在歧义或需要生成调查目标时才调用 LLM。候选目标表示优先调查对象，不等同于已经确认的根因系统。

完整原始 Trace 不直接放入 LLM 上下文。TraceAnalyser 应先完成裁剪、清洗和结构化，再向 LLM 提供关键 Span、上下游关系、异常摘要及来源定位。找不到 Trace 或调用链不完整时，主流程降级为基于日志和代码的逐系统调查。Pfinder 只作为调用链事实和证据来源，最终根因由主调查 Agent 结合 Trace、日志和代码证据判断。

### 日志访问边界

生产日志的查询权限、检索范围、裁剪和脱敏由主调查 Agent 统一控制。`LogParser` 通过日志 Provider 执行只读查询，对结果进行结构化、去重、排序、上下文截取和敏感信息脱敏，再将必要的日志证据交给后续分析节点。

CodeInvestigator 不直接访问生产日志平台，只接收主 Agent 提供的最小必要日志证据。如果代码调查发现证据不足，应返回结构化的补充证据请求，说明目标系统、建议时间范围、业务 Key 或 TraceID、日志特征及请求原因。主 Agent 校验权限、范围和预算后决定是否执行，并将新证据作为新的调查步骤记录。

### 根因验证边界

主调查 Agent 通过统一的 `Verifier` 门面验证根因候选，不直接依赖具体的验证方式。Verifier 统一集成 `HypothesisVerifier` 和 `RuntimeVerifier`，负责调用适用的验证器并汇总验证结论、支持证据、冲突证据、缺失证据及置信度。

第一版实现 `HypothesisVerifier`：综合 Trace、日志和代码证据检查根因候选是否成立，主动识别反例、证据冲突和缺失条件。它不直接搜索代码或访问生产数据；需要补充代码或日志证据时，向主 Agent 返回明确的调查请求，由主 Agent 调用 CodeInvestigator 或 LogParser 后重新发起验证。

第一版只保留 `RuntimeVerifier` 接口，用于未来接入流量回放、测试环境复现或其他动态验证能力，不提供真实实现，也不得触发生产操作。当运行时验证不可用或未执行时，Verifier 必须明确标记验证状态，不能将其解释为验证通过。调查是否继续及循环次数由 LangGraph 主流程控制，不由具体 Verifier 自行递归。

### 调查记录与 Memory 边界

调查任务的运行状态和历史故障案例是两类不同的数据。第一版必须实现 `InvestigationStore`，保存原始问题、每一步查询和工具调用、证据引用、根因候选及置信度变化、补充调查请求、验证结果、当前流程节点、终止原因和最终结果，用于 LangGraph 中断恢复、重试、审计和调查回放。Demo 阶段可以使用 LangGraph Checkpointer 配合简单的本地持久化实现。

历史案例复用通过 `CaseMemoryProvider` 接口隔离，第一版只保留接口，不引入向量数据库或相似案例存储实现。未来的 Case Memory 可以根据系统、异常类型、错误特征和业务场景检索历史案例，但检索结果只能作为调查线索，不能直接作为当前根因结论，仍需使用当前 Trace、日志和代码证据重新验证。只有经过确认或明确标注置信度的诊断结果才能写入，避免未经验证的模型推断污染 Memory。

### InvestigationStore 持久化方案

第一版使用 SQLite 作为单机 Demo 的本地持久化方案。LangGraph Checkpointer 负责保存图执行位置和流程恢复所需的状态；InvestigationStore 负责保存可审计的调查轨迹、证据引用、判断变化、验证结果、终止原因和 UsageMonitor 汇总。两者职责和访问接口保持逻辑分离，但 Demo 可以共用同一个 SQLite 文件。

InvestigationStore 不保存原始生产日志、完整代码内容、模型完整 Prompt 或访问凭证，只保存经过脱敏的必要摘要、来源引用和用量元数据。各调查步骤应支持幂等写入，进程重启后可以从最近的有效检查点继续，并避免重复记录已完成步骤。持久化能力通过接口隔离，为后续替换 PostgreSQL 等多实例存储保留空间；分布式锁、高可用和多实例并发不属于第一版范围。

### 交互层边界

第一版只提供 CLI，不开发 HTTP 接口或前端页面。CLI 接收问题描述、业务 Key、起始系统和时间范围等调查输入，在运行过程中展示当前调查步骤和 API 用量，结束时同时输出人类可读的诊断报告和结构化 JSON 结果。

核心调查流程通过独立的应用服务暴露，不依赖 CLI 的输入输出实现。CLI 只负责参数收集、触发调查、订阅进度事件和渲染结果；后续如需对接前端，可以在同一应用服务外包装 HTTP 接口，不改动核心领域逻辑和 LangGraph 调查图。HTTP API、Web UI、用户会话和多租户能力均不属于第一版范围。

### 失败、重试与降级边界

Provider 只对超时、限流和临时服务错误等可恢复失败进行有限次数重试，并使用退避策略；参数错误、认证或授权失败、资源不存在等确定性错误不自动重试。所有重试都必须保持调用幂等，并记录原始错误类型、尝试次数和最终结果。

LLMProvider 或 CodeAnalysisProvider 返回结构化格式错误时，允许进行一次针对格式的修复重试，仍失败则向主流程返回可观察错误。CodeInvestigator 因超时或预算终止时，应尽可能返回已经获得的部分证据和未完成项，不能丢弃整个调查结果。

Pfinder 无结果或调用链不完整时，主流程降级为基于日志和代码的逐系统调查；日志无结果时可以继续使用 Trace 和代码证据，但必须降低结论的充分程度并记录证据缺口。每个成功步骤完成后写入检查点，恢复时跳过已经幂等完成的步骤。所有失败、重试、修复和降级事件都写入 InvestigationStore，并计入 UsageMonitor，不能静默处理。

### RLM 与 RSI 演进边界

第一版不引入专门的 RLM 框架，先使用渐进检索、Trace 裁剪、日志分段、上下文摘要和 Codex 递归代码调查控制上下文规模。UsageMonitor 记录上下文规模、Token 消耗和调查轮次，只有在真实场景证明现有方案无法满足日志规模或递归调查需求后，再评估将可替换的 RLM 策略接入相关节点。

第一版不实现运行时自我改写。Agent 不得自行修改项目代码、Prompt、工具定义或调查规则。InvestigationStore 保存成功和失败的调查轨迹，后续可以离线分析这些轨迹，生成调查策略或 Prompt 的改进建议；任何改进都必须经过评测和人工审核，并以明确版本发布后才能生效。

通过 `InvestigationStrategyProvider` 预留策略加载边界，主 Agent 只加载配置指定的已发布策略版本。第一版仅定义接口并提供固定默认策略，不实现自动策略生成、自动评测或自动发布。

### 问题解析与上下文补全边界

`ClueExtractor` 只负责从用户描述中提取现象、业务 Key、时间范围、TraceID、起始系统等语义线索，并标记缺失项和不确定项，不负责生成或猜测企业内部资源地址。

`ContextResolver` 负责根据已提取的系统名称，通过受控的企业内部元数据 Provider 查询代码库、日志实例、运行环境和 Pfinder 服务标识等确定性信息。无法唯一解析系统或缺少必要信息时，应返回候选项或明确的补充信息请求，由主 Agent 决定是否询问用户或继续受限检索。代码库链接、实例地址等内部信息只能来自受控 API 或配置，不能由 LLM 自行生成。

### 代码工作区边界

企业内部元数据 Provider 负责提供目标系统的 Git 仓库地址以及故障时对应的 commit、tag 或发布版本，不直接向 Agent 提供零散代码内容。`GitWorkspaceManager` 负责临时工作区的业务策略和生命周期，并通过 `RepositoryWorkspacePort` 调用 `GitCliRepositoryAdapter` 完成具体 Git 操作。它为每次代码调查创建隔离的临时工作区，优先浅克隆指定版本，并将仓库、版本和本地工作区交给 CodeInvestigator。若暂时无法获取线上部署版本，可以在 Demo 中使用约定分支，但必须将版本不确定性记录为调查假设。

GitWorkspaceManager 只允许克隆受信任的内部 Git 域名，凭证通过安全的 credential helper 或服务身份提供，不得拼接到 URL、日志或模型输入中。第一版默认不拉取 submodule 和 Git LFS 大文件，不执行仓库脚本或其他项目代码。Codex 在只读沙箱中分析代码，代码证据必须保留仓库、commit、文件路径和行号。调查完成后清理临时工作区；按仓库和 commit 复用只读缓存作为后续优化，不纳入第一版。

### 调查终止与结论边界

主调查 Agent 在以下任一条件满足时终止当前调查：根因候选已经获得足够的 Trace、日志和代码证据并通过 HypothesisVerifier；缺少必须由用户补充的关键输入；达到最大调查深度、时间或 Token/成本预算；下一跳是当前无法访问的外部依赖；数据源无结果、无权限或持续失败且不存在其他有效调查路径。

诊断结果根据证据充分程度使用以下结论状态：

- `VERIFIED`：Trace、日志和代码等关键证据相互印证，并已通过适用的 Verifier。
- `SUPPORTED_HYPOTHESIS`：现有证据支持当前最佳假设，但仍缺少部分证据或验证。
- `UNRESOLVED`：无法形成可靠根因，只输出已完成的调查、阻塞原因、未决问题和下一步建议。

结论状态不能掩盖具体的验证范围。RuntimeVerifier 未执行或不可用时，即使 HypothesisVerifier 已通过，也必须明确披露“未完成运行时验证”，不得将静态验证表述为生产环境中的确定事实。因预算、权限或工具失败而终止时，应保留当前最佳假设，但结论状态和终止原因必须分别记录。

## 模块设计

1. ClueExtractor：只负责从用户描述中提取问题现象、业务 Key、时间范围、TraceID、起始系统等语义线索，并标记缺失项和不确定项，不查询或猜测企业内部资源地址。
2. ContextResolver：根据系统名称调用企业内部元数据 Provider，解析代码库、日志实例、运行环境和 Pfinder 服务标识等确定性上下文。无法唯一解析时返回候选项或补充信息请求，内部地址不能由 LLM 自行生成。
3. TraceFinder：用于定位问题所在的调用链，这里负责调用 Pfinder 工具的能力，返回调用的拓扑。
4. TraceAnalyser：用于分析调用链。某个请求可能会定位到一个或者多个调用链，需要先使用确定性逻辑完成筛选、清洗和异常节点识别，再生成带来源定位的结构化摘要和有序候选调查目标队列；只有存在歧义或需要规划调查目标时才调用 LLM。候选目标不是已确认的根因系统。该模块是主状态图中的节点或小型子图，不作为平级自治 Agent。
5. GitWorkspaceManager：根据 ContextResolver 提供的 Git 地址和目标版本管理隔离的临时只读工作区，负责受信任域名校验、克隆策略、生命周期和调查结束后的清理。具体 Git 命令通过 `RepositoryWorkspacePort` 委派给 `GitCliRepositoryAdapter`；第一版不拉取 submodule 和 Git LFS 大文件，不执行仓库代码。
6. CodeInvestigator：作为由主调查 Agent 调用的 Codex 子 Agent，接收临时代码工作区、问题描述、经过裁剪和脱敏的日志证据、关键 Span、方法或协议入口【RPC/MQ/HTTP 等】以及调查预算。在限定范围内自主搜索和阅读代码、追踪跨文件调用关系，并返回结构化代码证据、根因候选、未决问题和必要的补充证据请求。主流程通过 `CodeAnalysisProvider` 与其交互，并负责上下文裁剪、结果校验和是否继续调查的决策。CodeInvestigator 不直接访问生产日志平台。
7. LogParser：通过日志 Provider 执行受限的只读查询，定位问题日志、获取必要上下文，并完成结构化、去重、排序和脱敏。查询条件和范围由主调查 Agent 控制，所有查询及返回证据都需要记录到调查轨迹中。
8. Verifier：统一的根因验证入口，集成 `HypothesisVerifier` 和 `RuntimeVerifier`。第一版实现 HypothesisVerifier，用于综合 Trace、日志和代码证据验证根因候选、寻找反例并识别证据缺口；需要补充调查时向主 Agent 返回请求，不自行查询生产数据或递归执行。RuntimeVerifier 第一期只保留接口，供未来接入流量回放、测试环境复现等动态验证能力；未执行运行时验证时必须明确标记，不得视为验证通过。
9. InvestigationStore：第一版使用 SQLite 实现，用于持久化可审计的调查轨迹并支持回放；LangGraph Checkpointer 单独负责流程检查点和中断恢复。两者逻辑分离但可共用一个 SQLite 文件，并通过接口预留后续替换 PostgreSQL 等存储的能力。持久化内容不包含原始生产日志、完整代码、完整 Prompt 或凭证。
10. CaseMemoryProvider【一期只保留接口】：用于未来存储和检索历史故障案例。相似案例只能作为当前调查的线索，必须结合当前 Trace、日志和代码重新验证后才能形成结论；只有经过确认或明确标注置信度的结果才允许写入。
11. LLMProvider：主 LangGraph 使用的通用模型适配接口，负责模型调用、结构化输出、超时、重试和错误暴露。具体供应商和模型通过配置选择，不与 CodeAnalysisProvider 或 Codex SDK 耦合。
12. UsageMonitor：统一记录每个调查任务和步骤中的模型、Pfinder、日志及仓库相关 API 用量，包括调用次数、耗时、错误、重试和可获得的 Token/成本数据。只保存用量元数据，不保存敏感请求正文；用量不可得时明确标记为未知。
13. CLI：第一版唯一的交互入口，负责接收调查参数、展示步骤和用量、渲染人类可读报告并输出结构化 JSON。CLI 通过独立应用服务调用核心调查流程，不直接依赖 LangGraph 节点或具体 Provider。
14. InvestigationStrategyProvider【一期固定实现】：为主调查 Agent 提供指定版本的调查策略。第一版只加载随应用发布的固定默认策略，不允许运行时生成、修改或发布策略；未来可接入经过离线评测和人工审核的版本化策略。

## 详细设计

### 1. 技术与工程基线

第一版项目使用以下工程基线：

- Python 3.12，使用 `src` layout。
- LangGraph 负责主调查状态图和流程恢复。
- Python Codex SDK 负责 CodeInvestigator 子 Agent。
- uv 负责 Python 版本、虚拟环境、依赖和锁文件管理。
- 项目分发名使用 `pfinder-with-ai`，Python 包名使用 `pfinder_ai`，CLI 命令使用 `pfinder-ai`。
- `pyproject.toml` 声明项目与依赖，`uv.lock` 锁定实际安装版本并提交到版本库，`.venv` 不提交。
- 第一版不引入 HTTP 服务、前端框架和真实内部 API 客户端。

初始运行依赖计划包括 `langgraph`、`pydantic`、`pydantic-settings`、`typer`、`rich` 和 `openai-codex`；开发依赖包括 `pytest`、`pytest-asyncio`、`ruff` 和 `mypy`。SQLite Checkpointer 相关依赖在实现持久化切片时加入，HTTP 和具体 LLM SDK 在实际对接 Provider 时加入。

### 2. 分层与依赖方向

项目采用 Ports and Adapters 的分层方式，但保持单体应用，不拆分为多个服务：

```text
CLI / bootstrap
        |
        v
Application Service
        |
        +----> LangGraph nodes and routing
        +----> Domain services
        +----> Ports
                    ^
                    |
               Adapters
```

依赖规则如下：

- `domain` 只表达领域概念和规则，不依赖 LangGraph、Codex、SQLite 或公司 SDK。
- `ports` 定义核心流程需要的能力接口，可以依赖领域模型，但不能依赖具体 Adapter。
- `adapters` 实现 Ports，将外部返回转换为领域对象；供应商 SDK 对象不能进入 LangGraph State。
- `services` 实现不属于单个图节点的领域协作逻辑，可以依赖 Domain 和 Ports。
- `graph` 负责状态、节点包装、条件路由和图构建，不直接执行 Git、SQLite 或网络调用。
- `application` 负责启动一次调查、订阅进度、恢复任务和返回结果。
- `bootstrap.py` 是组合根，负责根据配置创建 Adapter、Service 和 LangGraph 实例。
- `cli.py` 只负责命令行输入输出，不包含调查业务逻辑。

### 3. 计划目录结构

```text
PfinderWithAI/
|-- pyproject.toml
|-- uv.lock
|-- .python-version
|-- .gitignore
|-- .env.example
|-- README.md
|-- AGENTS.md
|
|-- docs/
|   |-- Requirements.md
|   |-- Design.md
|   |-- DemoAcceptance.md
|   `-- InvestigationStateFlow.md
|
|-- memory/
|   |-- README.md
|   `-- PROJECT_MEMORY.md
|
|-- src/
|   `-- pfinder_ai/
|       |-- __init__.py
|       |-- bootstrap.py
|       |-- cli.py
|       |-- config.py
|       |
|       |-- application/
|       |   |-- service.py
|       |   `-- events.py
|       |
|       |-- domain/
|       |   |-- models.py
|       |   |-- enums.py
|       |   `-- errors.py
|       |
|       |-- graph/
|       |   |-- state.py
|       |   |-- builder.py
|       |   |-- routing.py
|       |   `-- nodes/
|       |       |-- clue_extractor.py
|       |       |-- context_resolver.py
|       |       |-- trace_finder.py
|       |       |-- trace_analyser.py
|       |       |-- log_parser.py
|       |       |-- code_investigator.py
|       |       |-- verifier.py
|       |       `-- result_builder.py
|       |
|       |-- ports/
|       |   |-- llm.py
|       |   |-- trace.py
|       |   |-- logs.py
|       |   |-- metadata.py
|       |   |-- code_analysis.py
|       |   |-- repository.py
|       |   |-- verification.py
|       |   |-- stores.py
|       |   `-- strategy.py
|       |
|       |-- adapters/
|       |   |-- fake/
|       |   |   `-- providers.py
|       |   |-- codex/
|       |   |   `-- code_analysis.py
|       |   |-- repository/
|       |   |   `-- git_cli.py
|       |   `-- sqlite/
|       |       |-- investigation_store.py
|       |       `-- checkpointer.py
|       |
|       |-- services/
|       |   |-- trace_analysis.py
|       |   |-- verification.py
|       |   `-- workspace_manager.py
|       |
|       |-- monitoring/
|       |   `-- usage.py
|       |
|       `-- strategies/
|           `-- default.py
|
`-- tests/
    |-- unit/
    |-- contract/
    |-- integration/
    `-- fixtures/
```

目录初始化时需要为 Python package 目录添加必要的 `__init__.py`。上图只列出第一版有明确职责的文件；真实 Pfinder、日志、元数据和 LLM Adapter 等到接口能力确定后再增加，不提前创建空实现。

### 4. 目录职责

| 路径 | 职责 |
| --- | --- |
| `bootstrap.py` | 应用组合根，根据配置装配 Ports、Adapters、Services、LangGraph 和持久化组件。 |
| `cli.py` | 实现 `pfinder-ai` 命令，收集输入、显示调查事件和用量、渲染最终报告与 JSON。 |
| `config.py` | 读取非敏感默认配置和环境变量；真实密钥不写入配置文件或仓库。 |
| `application/` | 提供启动、恢复和查询调查任务的应用级用例；对 CLI 隐藏 LangGraph 细节。 |
| `domain/` | 放置 Incident、Evidence、Hypothesis、InvestigationStep、VerificationResult、DiagnosisResult 等稳定领域概念和领域错误。 |
| `graph/` | 定义 InvestigationState、主图节点、条件边和 DecisionRouter。节点负责调用 Service 或 Port 并更新自己拥有的状态部分。 |
| `ports/` | 使用 Python Protocol 或抽象接口描述 LLM、Trace、日志、元数据、代码分析、仓库工作区、验证和持久化能力。 |
| `adapters/fake/` | 使用合成数据实现 Ports，优先跑通 `A -> B -> C/D` 的端到端开发和测试流程。 |
| `adapters/codex/` | 实现 CodeAnalysisProvider，将代码调查请求映射到 Python Codex SDK，并把结果转换为领域对象。 |
| `adapters/repository/` | 实现仓库操作 Port；第一版由 `git_cli.py` 包装本机 Git CLI。 |
| `adapters/sqlite/` | 实现 InvestigationStore 和 LangGraph Checkpointer 的 SQLite 持久化。 |
| `services/` | 放置 Trace 候选排序、Verifier 协调和临时工作区生命周期等跨节点协作逻辑。 |
| `monitoring/` | 实现 UsageMonitor，收集调用次数、耗时、重试、错误和可获得的 Token/成本数据。 |
| `strategies/` | 保存经过版本控制的固定调查策略；第一版不允许运行时修改。 |
| `tests/unit/` | 验证纯领域逻辑、路由、节点状态更新和错误分类。 |
| `tests/contract/` | 验证 Fake 与未来真实 Adapter 是否遵守相同的 Port 契约。 |
| `tests/integration/` | 验证 LangGraph、SQLite、Git 工作区和 Codex 等组件组合。 |
| `tests/fixtures/` | 保存合成或彻底匿名化的 Trace、日志和代码仓库测试数据。 |
| `memory/` | 保存可提交的跨设备开发上下文和接力说明；它不是运行时 CaseMemoryProvider 的数据目录。 |

### 5. Git Adapter 与 GitWorkspaceManager 的分工

`adapters/repository/git_cli.py` 不是 Git 服务，也不负责决定调查哪个仓库。它是 `RepositoryWorkspacePort` 的基础设施实现，用来把领域层的“准备指定版本代码工作区”请求转换成本机 Git CLI 操作。

```text
ContextResolver
      |
      v
GitWorkspaceManager          负责策略和生命周期
      |
      v
RepositoryWorkspacePort      定义核心需要的仓库能力
      |
      v
GitCliRepositoryAdapter      执行 clone/fetch/checkout/rev-parse
      |
      v
临时只读代码工作区
      |
      v
Codex CodeInvestigator
```

职责边界如下：

| 组件 | 职责 |
| --- | --- |
| ContextResolver | 提供系统对应的 Git 地址和期望版本，不执行 Git 命令。 |
| GitWorkspaceManager | 校验受信任域名、选择浅克隆策略、创建临时目录、记录版本假设、控制工作区生命周期并确保最终清理。 |
| RepositoryWorkspacePort | 定义准备工作区、解析实际 commit 和释放工作区所需的抽象能力，不暴露 subprocess 或 Git SDK 类型。 |
| GitCliRepositoryAdapter | 使用参数化的 Git 子进程执行必要命令，将退出码和标准错误映射为领域错误，并返回实际 checkout commit。 |
| CodeInvestigator | 只消费已准备好的工作区路径及版本信息，以只读沙箱分析代码。 |

GitCliRepositoryAdapter 第一版遵守以下约束：

- 不使用 `shell=True` 或拼接字符串命令，所有 Git 参数以参数数组传递。
- 不把用户名、Token 或其他凭证拼入仓库 URL、日志或模型输入。
- 默认浅克隆指定版本，不递归获取 submodule，不拉取 Git LFS 大文件。
- 不执行仓库脚本、构建命令、测试命令或 Git hook。
- 记录实际 commit，用于生成可复现的代码证据引用。
- Git 失败时返回结构化错误，由上层重试或降级，不在 Adapter 中猜测其他仓库或版本。

### 6. 第一阶段搭建范围

项目结构初始化只完成以下内容：

- uv 项目、Python package、CLI 入口和基础配置。
- Domain、Ports、Graph、Adapters 和 Services 的目录及最小可导入骨架。
- Fake Providers 和一个合成调查场景，用于验证依赖装配与状态流转。
- 基础单元测试、格式检查、静态类型检查和可直接运行的命令。
- README 和 AGENTS.md 中的安装、运行、检查和测试说明。

初始化阶段不对接 Pfinder、生产日志、系统元数据或真实 LLMProvider，也不实现 HTTP API、前端、RuntimeVerifier 和 Case Memory。

### 7. 当前骨架落地状态

截至 2026-08-15，目录骨架、领域模型、Ports、LangGraph 主图、Fake 纵向链路、Git CLI Adapter、Codex SDK Adapter、SQLite InvestigationStore、UsageMonitor、应用服务和 CLI 已落地。Fake CLI 可以从合成输入运行到结构化诊断结果，并保存输入、步骤和结果。

以下内容仍是明确缺口，不应被描述为已经可用：

- 公司内部 Pfinder、日志、元数据和 LLM API 的真实 Adapter。
- LangGraph SQLite Checkpointer；现有 SQLite Adapter 只实现 InvestigationStore。
- CLI 对真实 Codex 和企业数据源的装配及账号联调。
- 所有 Provider 的 UsageMonitor 统一代理和单次调查用量回写。
- RuntimeVerifier、HTTP API、前端、权限平台和运行时 Case Memory。

跨设备开发上下文保存到仓库根目录的 `memory/`。该目录只记录项目级事实、决策和接力说明，禁止写入真实日志、凭证、内部地址或客户数据，也不能替代未来的 `CaseMemoryProvider`。

