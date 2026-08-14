"""使用全套 Fake Providers 跑通主调查图。"""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pfinder_ai.adapters.fake import (
    FakeCodeAnalysisProvider,
    FakeLogProvider,
    FakeMetadataProvider,
    FakeRepositoryAdapter,
    FakeTraceProvider,
    InMemoryInvestigationStore,
)
from pfinder_ai.domain.enums import (
    ConclusionStatus,
    EvidenceSource,
    ExecutionStatus,
)
from pfinder_ai.domain.models import (
    Evidence,
    IncidentInput,
    SystemContext,
    TimeRange,
    TraceCandidate,
    TraceSpan,
)
from pfinder_ai.graph.builder import build_investigation_graph
from pfinder_ai.graph.dependencies import GraphDependencies
from pfinder_ai.graph.policy import GraphExecutionPolicy
from pfinder_ai.graph.state import InvestigationState
from pfinder_ai.services.workspace_manager import GitWorkspaceManager


def test_fake_graph_produces_traceable_verified_result(tmp_path: Path) -> None:
    """合成故障必须经过 Trace、日志和代码证据形成可回放结果。"""

    workspace_base = tmp_path
    now = datetime.now(UTC)
    store = InMemoryInvestigationStore()
    repository = FakeRepositoryAdapter()
    dependencies = GraphDependencies(
        metadata=FakeMetadataProvider(
            {
                "system-a": SystemContext(
                    system="system-a",
                    repository_url="https://git.example.local/system-a.git",
                    revision="release-synthetic",
                ),
                "system-b": SystemContext(
                    system="system-b",
                    repository_url="https://git.example.local/system-b.git",
                    revision="release-synthetic",
                    log_source="synthetic-system-b-log",
                ),
            }
        ),
        traces=FakeTraceProvider(
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
        ),
        logs=FakeLogProvider(
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
        ),
        code_analysis=FakeCodeAnalysisProvider(),
        workspaces=GitWorkspaceManager(
            repository,
            trusted_hosts=frozenset({"git.example.local"}),
            base_directory=workspace_base,
        ),
        store=store,
        policy=GraphExecutionPolicy(max_depth=4, max_provider_calls=20),
    )
    graph = build_investigation_graph(dependencies)
    incident = IncidentInput(
        description="合成订单创建失败",
        business_keys={"order_id": "synthetic-001"},
        start_system="system-a",
        time_range=TimeRange(
            start=now - timedelta(minutes=5),
            end=now,
        ),
    )

    final_state = asyncio.run(
        graph.ainvoke(
            InvestigationState(
                investigation_id="investigation-synthetic",
                incident=incident,
                investigation_depth=0,
                provider_call_count=0,
                started_at=now,
                execution_status=ExecutionStatus.RUNNING,
            ),
            {"recursion_limit": 50},
        )
    )
    result = final_state["result"]

    assert result is not None
    assert result.conclusion_status is ConclusionStatus.VERIFIED
    assert {item.source for item in result.evidence} == {
        EvidenceSource.TRACE,
        EvidenceSource.LOG,
        EvidenceSource.CODE,
    }
    assert result.verification is not None
    assert result.verification.runtime_verified is False
    assert result.investigation_steps[-1].name == "persist_result"
    assert asyncio.run(store.load_result("investigation-synthetic")) == result
    assert repository.released_workspaces
    assert not repository.released_workspaces[0].exists()
