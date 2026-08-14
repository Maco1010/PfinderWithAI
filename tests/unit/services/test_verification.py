"""HypothesisVerifier 的证据充分性测试。"""

from pfinder_ai.domain.enums import EvidenceSource, NextAction, VerificationStatus
from pfinder_ai.domain.models import Evidence, Hypothesis
from pfinder_ai.services.verification import HypothesisVerifier


def _evidence(evidence_id: str, source: EvidenceSource) -> Evidence:
    """生成不包含生产数据的测试证据。"""

    return Evidence(
        evidence_id=evidence_id,
        source=source,
        system="system-d",
        summary=f"{source.value} synthetic evidence",
        locator=f"fixture={evidence_id}",
    )


def test_verifier_requests_code_when_only_log_supports_hypothesis() -> None:
    """只有日志证据时不能把根因假设标记为验证通过。"""

    hypothesis = Hypothesis(
        hypothesis_id="hypothesis-1",
        statement="连接池耗尽导致交易超时",
        target_system="system-d",
        confidence=0.85,
        supporting_evidence_ids=("log-1",),
    )

    result = HypothesisVerifier().verify(
        hypothesis,
        (_evidence("log-1", EvidenceSource.LOG),),
    )

    assert result.status is VerificationStatus.NEEDS_EVIDENCE
    assert result.next_action is NextAction.INVESTIGATE_CODE


def test_verifier_passes_when_log_and_code_evidence_agree() -> None:
    """日志和代码证据相互印证时允许通过静态验证。"""

    hypothesis = Hypothesis(
        hypothesis_id="hypothesis-1",
        statement="连接池耗尽导致交易超时",
        target_system="system-d",
        confidence=0.85,
        supporting_evidence_ids=("log-1", "code-1"),
    )

    result = HypothesisVerifier().verify(
        hypothesis,
        (
            _evidence("log-1", EvidenceSource.LOG),
            _evidence("code-1", EvidenceSource.CODE),
        ),
    )

    assert result.status is VerificationStatus.PASSED
    assert result.runtime_verified is False

