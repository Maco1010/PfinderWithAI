"""LangGraph 主调查流程使用的可序列化状态。"""

from collections.abc import Callable, Hashable
from datetime import datetime
from typing import Annotated, TypedDict

from pfinder_ai.domain.enums import ExecutionStatus, NextAction
from pfinder_ai.domain.models import (
    DiagnosisResult,
    Evidence,
    Hypothesis,
    IncidentInput,
    InvestigationErrorRecord,
    InvestigationStep,
    InvestigationTarget,
    NextHop,
    SystemContext,
    TraceCandidate,
    UsageRecord,
    VerificationResult,
)
from pfinder_ai.ports.code_analysis import SupplementalEvidenceRequest


def _merge_unique[T](
    left: tuple[T, ...],
    right: tuple[T, ...],
    key: Callable[[T], Hashable],
) -> tuple[T, ...]:
    """按稳定业务键追加新元素，并保留首次出现的版本和顺序。"""

    merged = list(left)
    seen = {key(item) for item in left}
    for item in right:
        item_key = key(item)
        if item_key in seen:
            continue
        seen.add(item_key)
        merged.append(item)
    return tuple(merged)


def merge_evidence(
    left: tuple[Evidence, ...],
    right: tuple[Evidence, ...],
) -> tuple[Evidence, ...]:
    """按证据编号进行幂等追加，避免重试产生重复证据。"""

    return _merge_unique(left, right, lambda item: item.evidence_id)


def merge_hypotheses(
    left: tuple[Hypothesis, ...],
    right: tuple[Hypothesis, ...],
) -> tuple[Hypothesis, ...]:
    """按假设编号追加根因候选。"""

    return _merge_unique(left, right, lambda item: item.hypothesis_id)


def merge_targets(
    left: tuple[InvestigationTarget, ...],
    right: tuple[InvestigationTarget, ...],
) -> tuple[InvestigationTarget, ...]:
    """按目标编号追加调查候选，保留既有优先级顺序。"""

    return _merge_unique(left, right, lambda item: item.target_id)


def merge_next_hops(
    left: tuple[NextHop, ...],
    right: tuple[NextHop, ...],
) -> tuple[NextHop, ...]:
    """按目标系统和发现证据去重新发现的 Trace 外依赖。"""

    return _merge_unique(
        left,
        right,
        lambda item: (
            item.target_system.casefold(),
            item.discovered_by_evidence_id,
        ),
    )


def merge_supplemental_requests(
    left: tuple[SupplementalEvidenceRequest, ...],
    right: tuple[SupplementalEvidenceRequest, ...],
) -> tuple[SupplementalEvidenceRequest, ...]:
    """合并 CodeInvestigator 提出的补充证据请求。"""

    return _merge_unique(
        left,
        right,
        lambda item: (item.action, item.reason, item.search_hints),
    )


def merge_steps(
    left: tuple[InvestigationStep, ...],
    right: tuple[InvestigationStep, ...],
) -> tuple[InvestigationStep, ...]:
    """按步骤编号幂等追加可审计调查轨迹。"""

    return _merge_unique(left, right, lambda item: item.step_id)


def merge_errors(
    left: tuple[InvestigationErrorRecord, ...],
    right: tuple[InvestigationErrorRecord, ...],
) -> tuple[InvestigationErrorRecord, ...]:
    """合并已脱敏错误，同时保留不同重试轮次。"""

    return _merge_unique(
        left,
        right,
        lambda item: (item.step_name, item.kind, item.message, item.attempt),
    )


def append_usage_records(
    left: tuple[UsageRecord, ...],
    right: tuple[UsageRecord, ...],
) -> tuple[UsageRecord, ...]:
    """追加每一次真实发生的 Provider 调用用量。"""

    return left + right


def merge_strings(
    left: tuple[str, ...],
    right: tuple[str, ...],
) -> tuple[str, ...]:
    """按精确值追加字符串集合，并维持稳定顺序。"""

    return _merge_unique(left, right, lambda item: item)


def merge_system_names(
    left: tuple[str, ...],
    right: tuple[str, ...],
) -> tuple[str, ...]:
    """按不区分大小写的系统名追加已访问集合。"""

    return _merge_unique(left, right, str.casefold)


def merge_system_contexts(
    left: dict[str, SystemContext],
    right: dict[str, SystemContext],
) -> dict[str, SystemContext]:
    """合并系统上下文，右侧显式解析结果覆盖旧值。"""

    return {**left, **right}


class InvestigationState(TypedDict, total=False):
    """一次调查的最小共享状态。

    状态只保存领域对象、摘要和引用，不保存原始日志、完整代码、凭证、
    完整提示词或 CodeInvestigator 的内部对话。
    """

    # 应用服务创建图输入时必须提供这两个字段；节点更新可以只返回局部字段。
    investigation_id: str
    incident: IncidentInput

    start_context: SystemContext
    current_context: SystemContext | None
    system_contexts: Annotated[dict[str, SystemContext], merge_system_contexts]

    trace_candidates: tuple[TraceCandidate, ...]
    target_queue: Annotated[tuple[InvestigationTarget, ...], merge_targets]
    current_target: InvestigationTarget | None
    visited_target_ids: Annotated[tuple[str, ...], merge_strings]
    visited_systems: Annotated[tuple[str, ...], merge_system_names]

    evidence: Annotated[tuple[Evidence, ...], merge_evidence]
    hypotheses: Annotated[tuple[Hypothesis, ...], merge_hypotheses]
    current_hypothesis: Hypothesis | None
    verification: VerificationResult | None
    supplemental_requests: Annotated[
        tuple[SupplementalEvidenceRequest, ...],
        merge_supplemental_requests,
    ]
    pending_requests: tuple[SupplementalEvidenceRequest, ...]
    next_hops: Annotated[tuple[NextHop, ...], merge_next_hops]
    enqueued_next_hop_ids: Annotated[tuple[str, ...], merge_strings]
    unresolved_questions: Annotated[tuple[str, ...], merge_strings]

    investigation_steps: Annotated[tuple[InvestigationStep, ...], merge_steps]
    errors: Annotated[tuple[InvestigationErrorRecord, ...], merge_errors]
    usage_records: Annotated[tuple[UsageRecord, ...], append_usage_records]

    investigation_depth: int
    provider_call_count: int
    started_at: datetime
    execution_status: ExecutionStatus
    next_action: NextAction | None
    termination_reason: str | None
    result: DiagnosisResult | None
