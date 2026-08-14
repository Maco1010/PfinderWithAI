"""统一 Verifier 中的确定性 HypothesisVerifier 基线。"""

from dataclasses import dataclass

from pfinder_ai.domain.enums import EvidenceSource, NextAction, VerificationStatus
from pfinder_ai.domain.models import Evidence, Hypothesis, VerificationResult


@dataclass(frozen=True, slots=True)
class VerificationPolicy:
    """第一版静态验证使用的最小策略。"""

    minimum_confidence: float = 0.7


class HypothesisVerifier:
    """检查根因假设是否被现有证据真实引用。

    该实现是可测试的确定性基线，不代替后续 LLM 反证分析。它首先保证
    假设引用的 Evidence 确实存在，并要求日志和代码证据相互印证。
    """

    def __init__(self, policy: VerificationPolicy | None = None) -> None:
        self._policy = policy or VerificationPolicy()

    def verify(
        self,
        hypothesis: Hypothesis,
        evidence: tuple[Evidence, ...],
    ) -> VerificationResult:
        """验证一个根因候选并给出明确的补充调查动作。"""

        evidence_by_id = {item.evidence_id: item for item in evidence}
        missing_references = tuple(
            evidence_id
            for evidence_id in hypothesis.supporting_evidence_ids
            if evidence_id not in evidence_by_id
        )
        available_conflicts = tuple(
            evidence_id
            for evidence_id in hypothesis.conflicting_evidence_ids
            if evidence_id in evidence_by_id
        )

        if available_conflicts:
            return VerificationResult(
                status=VerificationStatus.REJECTED,
                summary="现有证据与根因候选冲突，需要调查其他候选目标。",
                conflicting_evidence_ids=available_conflicts,
                next_action=NextAction.SELECT_TRACE_CANDIDATE,
            )

        if missing_references:
            return VerificationResult(
                status=VerificationStatus.NEEDS_EVIDENCE,
                summary="根因候选引用了尚未采集到的证据。",
                missing_evidence=missing_references,
                next_action=NextAction.INVESTIGATE_CODE,
            )

        supporting = tuple(
            evidence_by_id[evidence_id]
            for evidence_id in hypothesis.supporting_evidence_ids
            if evidence_id in evidence_by_id
        )
        sources = {item.source for item in supporting}

        if EvidenceSource.LOG not in sources:
            return self._needs_source(
                hypothesis,
                missing="缺少支持该假设的日志证据",
                next_action=NextAction.GATHER_LOGS,
            )
        if EvidenceSource.CODE not in sources:
            return self._needs_source(
                hypothesis,
                missing="缺少支持该假设的代码证据",
                next_action=NextAction.INVESTIGATE_CODE,
            )
        if hypothesis.confidence < self._policy.minimum_confidence:
            return VerificationResult(
                status=VerificationStatus.NEEDS_EVIDENCE,
                summary="日志与代码证据存在，但当前置信度尚未达到验证阈值。",
                supporting_evidence_ids=hypothesis.supporting_evidence_ids,
                missing_evidence=("需要补充能够提高或否定当前假设的证据",),
                next_action=NextAction.INVESTIGATE_CODE,
            )

        return VerificationResult(
            status=VerificationStatus.PASSED,
            summary="日志与代码证据相互印证，静态假设验证通过。",
            supporting_evidence_ids=hypothesis.supporting_evidence_ids,
            next_action=NextAction.FINISH,
            runtime_verified=False,
        )

    def _needs_source(
        self,
        hypothesis: Hypothesis,
        *,
        missing: str,
        next_action: NextAction,
    ) -> VerificationResult:
        """构造缺少某类证据时的一致返回值。"""

        return VerificationResult(
            status=VerificationStatus.NEEDS_EVIDENCE,
            summary=missing,
            supporting_evidence_ids=hypothesis.supporting_evidence_ids,
            missing_evidence=(missing,),
            next_action=next_action,
        )

