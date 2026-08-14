"""Fake Providers 对核心 Port 契约的基础验证。"""

import asyncio
from datetime import UTC, datetime, timedelta

from pfinder_ai.adapters.fake import (
    FakeLogProvider,
    FakeMetadataProvider,
    FakeTraceProvider,
)
from pfinder_ai.domain.enums import EvidenceSource, TargetSource
from pfinder_ai.domain.models import (
    Evidence,
    IncidentInput,
    InvestigationTarget,
    SystemContext,
    TimeRange,
    TraceCandidate,
)
from pfinder_ai.ports.logs import LogQuery
from pfinder_ai.ports.trace import TraceQuery


def test_fake_providers_preserve_query_limits_and_domain_types() -> None:
    """Fake 与未来真实 Adapter 应遵守相同的范围和返回类型。"""

    now = datetime.now(UTC)
    incident = IncidentInput(
        description="合成问题",
        business_keys={"order_id": "synthetic"},
        start_system="system-a",
        time_range=TimeRange(start=now - timedelta(minutes=5), end=now),
    )
    context = SystemContext(system="system-a", log_source="synthetic-log")
    metadata = FakeMetadataProvider({"system-a": context})
    traces = FakeTraceProvider(
        tuple(
            TraceCandidate(
                trace_id=f"trace-{index}",
                match_score=0.9,
                match_reason="合成匹配",
            )
            for index in range(3)
        )
    )

    resolution = asyncio.run(metadata.resolve_system("SYSTEM-A"))
    candidates = asyncio.run(
        traces.find_candidates(
            TraceQuery(
                incident=incident,
                start_context=context,
                limit=2,
            )
        )
    )

    assert resolution.candidates == (context,)
    assert len(candidates) == 2


def test_fake_log_provider_returns_only_configured_system_evidence() -> None:
    """日志替身不能把其他系统证据混入当前查询。"""

    evidence = Evidence(
        evidence_id="log:system-b:1",
        source=EvidenceSource.LOG,
        summary="合成超时",
        locator="synthetic-log:1",
        system="system-b",
    )
    provider = FakeLogProvider({"system-b": (evidence,)})
    incident = IncidentInput(
        description="合成问题",
        start_system="system-a",
        trace_id="trace-1",
    )
    target_context = SystemContext(system="system-b")
    target = InvestigationTarget(
        target_id="trace-1:span-1",
        system="system-b",
        source=TargetSource.TRACE_CANDIDATE,
        reason="合成异常",
        priority=0,
    )
    result = asyncio.run(
        provider.query(
            LogQuery(
                incident=incident,
                target=target,
                system_context=target_context,
                max_entries=1,
            )
        )
    )

    assert result == (evidence,)
