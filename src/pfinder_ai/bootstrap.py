"""根据配置装配本地 Demo 的应用依赖。"""

from dataclasses import dataclass

from pfinder_ai.adapters.fake import (
    FakeCodeAnalysisProvider,
    FakeLogProvider,
    FakeMetadataProvider,
    FakeRepositoryAdapter,
    FakeTraceProvider,
)
from pfinder_ai.adapters.llm import GatewayLLMProvider, GatewayLLMSettings
from pfinder_ai.adapters.sqlite import SQLiteInvestigationStore
from pfinder_ai.application import (
    InvestigationApplicationService,
    InvestigationEventSink,
    NullInvestigationEventSink,
)
from pfinder_ai.config import AppSettings
from pfinder_ai.domain.enums import EvidenceSource
from pfinder_ai.domain.models import (
    Evidence,
    SystemContext,
    TraceCandidate,
    TraceSpan,
)
from pfinder_ai.graph.builder import build_investigation_graph
from pfinder_ai.graph.dependencies import GraphDependencies
from pfinder_ai.graph.policy import GraphExecutionPolicy
from pfinder_ai.monitoring import UsageMonitor
from pfinder_ai.ports.llm import LLMProvider
from pfinder_ai.services.workspace_manager import GitWorkspaceManager


@dataclass(frozen=True, slots=True)
class ApplicationBundle:
    """向入口层暴露应用服务和可查看的运行时组件。"""

    service: InvestigationApplicationService
    store: SQLiteInvestigationStore
    usage_monitor: UsageMonitor


def build_application(
    settings: AppSettings | None = None,
    *,
    event_sink: InvestigationEventSink | None = None,
) -> ApplicationBundle:
    """装配合成数据源，并按显式配置选择是否调用真实模型网关。"""

    resolved_settings = settings or AppSettings()
    if resolved_settings.runtime_mode != "fake":
        raise ValueError("当前骨架只支持 fake 运行模式")

    store = SQLiteInvestigationStore(resolved_settings.database_path)
    usage_monitor = UsageMonitor()
    llm = build_llm_provider(resolved_settings, usage_monitor)
    repository = FakeRepositoryAdapter()
    metadata = FakeMetadataProvider(
        {
            "system-a": SystemContext(
                system="system-a",
                repository_url="https://git.example.local/system-a.git",
                revision="release-synthetic",
                log_source="synthetic-system-a-log",
            ),
            "system-b": SystemContext(
                system="system-b",
                repository_url="https://git.example.local/system-b.git",
                revision="release-synthetic",
                log_source="synthetic-system-b-log",
            ),
        }
    )
    traces = FakeTraceProvider(
        (
            TraceCandidate(
                trace_id="trace-synthetic",
                match_score=0.98,
                match_reason="合成业务标识和时间范围匹配",
                spans=(
                    TraceSpan(
                        span_id="span-a",
                        system="system-a",
                        operation="submit_order",
                        duration_ms=40,
                        status="ok",
                    ),
                    TraceSpan(
                        span_id="span-b",
                        parent_span_id="span-a",
                        system="system-b",
                        operation="create_order",
                        duration_ms=520,
                        status="error",
                        error_summary="synthetic downstream timeout",
                    ),
                ),
            ),
        )
    )
    logs = FakeLogProvider(
        {
            "system-b": (
                Evidence(
                    evidence_id="log:system-b:timeout",
                    source=EvidenceSource.LOG,
                    summary="调用下游时发生合成超时",
                    locator="synthetic-system-b-log:entry-1",
                    system="system-b",
                ),
            )
        }
    )
    dependencies = GraphDependencies(
        metadata=metadata,
        traces=traces,
        logs=logs,
        code_analysis=FakeCodeAnalysisProvider(),
        workspaces=GitWorkspaceManager(
            repository,
            trusted_hosts=frozenset(resolved_settings.trusted_git_hosts),
            base_directory=resolved_settings.workspace_base_directory,
        ),
        store=store,
        policy=GraphExecutionPolicy(
            max_depth=resolved_settings.max_depth,
            max_provider_calls=resolved_settings.max_provider_calls,
            max_elapsed_seconds=resolved_settings.max_elapsed_seconds,
        ),
        llm=llm,
        trace_candidate_limit=resolved_settings.trace_candidate_limit,
        log_max_entries=resolved_settings.log_max_entries,
    )
    graph = build_investigation_graph(dependencies)
    service = InvestigationApplicationService(
        graph=graph,
        store=store,
        recursion_limit=resolved_settings.graph_recursion_limit,
        event_sink=event_sink or NullInvestigationEventSink(),
    )
    return ApplicationBundle(
        service=service,
        store=store,
        usage_monitor=usage_monitor,
    )


def build_llm_provider(
    settings: AppSettings,
    usage_monitor: UsageMonitor,
) -> LLMProvider | None:
    """根据显式配置构造主流程模型 Provider，默认保持禁用。"""

    if settings.llm_provider == "disabled":
        return None
    if (
        settings.llm_base_url is None
        or settings.llm_api_key is None
        or settings.llm_model is None
    ):
        raise ValueError("模型网关配置不完整")
    return GatewayLLMProvider(
        GatewayLLMSettings(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            protocol=settings.llm_protocol,
            auth_style=settings.llm_auth_style,
            timeout_seconds=settings.llm_timeout_seconds,
            max_tokens=settings.llm_max_tokens,
            max_retries=settings.llm_max_retries,
            retry_backoff_seconds=settings.llm_retry_backoff_seconds,
            allow_insecure_http=settings.llm_allow_insecure_http,
        ),
        usage_monitor=usage_monitor,
    )
