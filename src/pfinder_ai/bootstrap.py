"""根据配置装配本地 Demo 的应用依赖。"""

from dataclasses import dataclass

from pfinder_ai.adapters.fake import (
    FakeCodeAnalysisProvider,
    FakeLogProvider,
    FakeMetadataProvider,
    FakeRepositoryAdapter,
    FakeTraceProvider,
)
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
    """装配当前唯一可运行的全合成 Demo 模式。"""

    resolved_settings = settings or AppSettings()
    if resolved_settings.runtime_mode != "fake":
        raise ValueError("当前骨架只支持 fake 运行模式")

    store = SQLiteInvestigationStore(resolved_settings.database_path)
    usage_monitor = UsageMonitor()
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
