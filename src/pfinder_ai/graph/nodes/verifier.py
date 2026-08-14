"""统一执行静态根因假设验证的节点。"""

from dataclasses import dataclass

from pfinder_ai.domain.enums import NextAction, VerificationStatus
from pfinder_ai.domain.models import InvestigationStep, VerificationResult
from pfinder_ai.graph.nodes.common import make_step_id, next_hop_id
from pfinder_ai.graph.state import InvestigationState
from pfinder_ai.services.verification import HypothesisVerifier


@dataclass(frozen=True, slots=True)
class VerifierNode:
    """运行 HypothesisVerifier；RuntimeVerifier 第一版不在此执行。"""

    verifier: HypothesisVerifier

    def __call__(self, state: InvestigationState) -> InvestigationState:
        """验证当前根因候选，或为无候选情况选择可解释的下一步。"""

        hypothesis = state.get("current_hypothesis")
        if hypothesis is None:
            action = self._fallback_action(state)
            verification = VerificationResult(
                status=VerificationStatus.NEEDS_EVIDENCE,
                summary="当前目标尚未形成可验证的根因候选。",
                missing_evidence=("缺少可验证的根因候选",),
                next_action=action,
                runtime_verified=False,
            )
        else:
            verification = self.verifier.verify(
                hypothesis,
                state.get("evidence", ()),
            )

        step = InvestigationStep(
            step_id=make_step_id(state, "hypothesis_verifier"),
            name="hypothesis_verifier",
            target_system=(
                hypothesis.target_system if hypothesis is not None else None
            ),
            evidence_ids=(
                verification.supporting_evidence_ids
                + verification.conflicting_evidence_ids
            ),
            decision=verification.summary,
            confidence=hypothesis.confidence if hypothesis is not None else None,
            next_action=verification.next_action,
        )
        return {
            "verification": verification,
            "next_action": verification.next_action,
            "investigation_steps": (step,),
        }

    def _fallback_action(self, state: InvestigationState) -> NextAction:
        """优先满足补充证据请求，再选择新依赖或 Trace 候选。"""

        pending_actions = {
            request.action for request in state.get("pending_requests", ())
        }
        if NextAction.GATHER_LOGS in pending_actions:
            return NextAction.GATHER_LOGS
        if NextAction.INVESTIGATE_CODE in pending_actions:
            return NextAction.INVESTIGATE_CODE

        enqueued = set(state.get("enqueued_next_hop_ids", ()))
        if any(
            next_hop_id(item) not in enqueued
            for item in state.get("next_hops", ())
        ):
            return NextAction.INVESTIGATE_DISCOVERED_DEPENDENCY

        visited = set(state.get("visited_target_ids", ()))
        if any(
            target.target_id not in visited
            for target in state.get("target_queue", ())
        ):
            return NextAction.SELECT_TRACE_CANDIDATE
        return NextAction.FINISH
