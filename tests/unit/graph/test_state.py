"""调查状态 Reducer 的幂等和顺序语义测试。"""

from pfinder_ai.domain.enums import EvidenceSource, TargetSource
from pfinder_ai.domain.models import Evidence, InvestigationTarget, SystemContext
from pfinder_ai.graph.state import (
    merge_evidence,
    merge_system_contexts,
    merge_system_names,
    merge_targets,
)


def test_evidence_reducer_deduplicates_retried_result() -> None:
    """节点重试返回相同证据编号时不能重复污染状态。"""

    evidence = Evidence(
        evidence_id="log:system-b:1",
        source=EvidenceSource.LOG,
        summary="订单状态写入失败",
        locator="log-query:synthetic:1",
        system="system-b",
    )

    assert merge_evidence((evidence,), (evidence,)) == (evidence,)


def test_target_reducer_preserves_existing_queue_order() -> None:
    """后发现的依赖只能追加，不能打乱 Trace 候选的既有顺序。"""

    first = InvestigationTarget(
        target_id="trace-1:span-1",
        system="system-b",
        source=TargetSource.TRACE_CANDIDATE,
        reason="显式异常",
        priority=0,
    )
    second = InvestigationTarget(
        target_id="trace-1:span-2",
        system="system-c",
        source=TargetSource.TRACE_CANDIDATE,
        reason="上游超时",
        priority=1,
    )

    assert merge_targets((first,), (first, second)) == (first, second)


def test_system_reducers_handle_identity_and_context_updates() -> None:
    """系统访问去重忽略大小写，而上下文允许显式刷新。"""

    old_context = SystemContext(system="system-b", revision="old")
    new_context = SystemContext(system="system-b", revision="new")

    assert merge_system_names(("System-B",), ("system-b", "system-c")) == (
        "System-B",
        "system-c",
    )
    assert merge_system_contexts(
        {"system-b": old_context},
        {"system-b": new_context},
    ) == {"system-b": new_context}
