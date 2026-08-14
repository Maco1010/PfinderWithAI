"""根据当前证据充分度构建最终结构化诊断。"""

from decimal import Decimal

from pfinder_ai.domain.enums import (
    ConclusionStatus,
    ExecutionStatus,
    NextAction,
    VerificationStatus,
)
from pfinder_ai.domain.models import (
    DiagnosisResult,
    InvestigationStep,
    UsageSummary,
)
from pfinder_ai.graph.nodes.common import make_step_id, merge_text_values
from pfinder_ai.graph.state import InvestigationState, merge_steps


class ResultBuilderNode:
    """区分流程执行状态、静态证据结论和运行时验证范围。"""

    def __call__(self, state: InvestigationState) -> InvestigationState:
        """输出当前最佳结论，并保留证据、未决问题和完整调查轨迹。"""

        hypothesis = state.get("current_hypothesis")
        verification = state.get("verification")
        conclusion = self._conclusion_status(state)
        execution = state.get("execution_status", ExecutionStatus.RUNNING)
        if execution is ExecutionStatus.RUNNING:
            execution = ExecutionStatus.COMPLETED

        termination_reason = (
            state.get("termination_reason")
            or "调查流程已基于当前证据结束"
        )
        summary = self._summary(conclusion, hypothesis.statement if hypothesis else None)
        unresolved = state.get("unresolved_questions", ())
        if verification is not None:
            unresolved = merge_text_values(unresolved, verification.missing_evidence)

        recommended_actions: tuple[str, ...] = ()
        if execution is ExecutionStatus.WAITING_INPUT:
            recommended_actions += ("补充缺失的调查输入后恢复任务",)
        if conclusion is not ConclusionStatus.VERIFIED:
            recommended_actions += ("根据未决问题补充证据后重新验证",)
        if verification is not None and not verification.runtime_verified:
            recommended_actions += ("如需动态确认，请在受控环境接入 RuntimeVerifier",)
            summary += " 当前未执行运行时验证。"

        final_step = InvestigationStep(
            step_id=make_step_id(state, "result_builder"),
            name="result_builder",
            target_system=hypothesis.target_system if hypothesis else None,
            evidence_ids=(
                hypothesis.supporting_evidence_ids if hypothesis else ()
            ),
            decision=summary,
            confidence=hypothesis.confidence if hypothesis else 0,
            next_action=NextAction.FINISH,
        )
        steps = merge_steps(state.get("investigation_steps", ()), (final_step,))
        result = DiagnosisResult(
            execution_status=execution,
            conclusion_status=conclusion,
            summary=summary,
            root_cause=hypothesis.statement if hypothesis else None,
            confidence=hypothesis.confidence if hypothesis else 0,
            evidence=state.get("evidence", ()),
            investigation_steps=steps,
            verification=verification,
            unresolved_questions=unresolved,
            recommended_actions=recommended_actions,
            termination_reason=termination_reason,
            usage=self._usage_summary(state),
        )
        return {
            "execution_status": execution,
            "termination_reason": termination_reason,
            "investigation_steps": (final_step,),
            "result": result,
        }

    def _conclusion_status(self, state: InvestigationState) -> ConclusionStatus:
        """只在静态验证明确通过时使用 VERIFIED。"""

        hypothesis = state.get("current_hypothesis")
        verification = state.get("verification")
        if (
            hypothesis is not None
            and verification is not None
            and verification.status is VerificationStatus.PASSED
        ):
            return ConclusionStatus.VERIFIED
        if (
            hypothesis is not None
            and hypothesis.supporting_evidence_ids
            and (
                verification is None
                or verification.status is not VerificationStatus.REJECTED
            )
        ):
            return ConclusionStatus.SUPPORTED_HYPOTHESIS
        return ConclusionStatus.UNRESOLVED

    def _summary(
        self,
        conclusion: ConclusionStatus,
        statement: str | None,
    ) -> str:
        """生成不夸大当前证据范围的简要结论。"""

        if conclusion is ConclusionStatus.VERIFIED and statement:
            return f"静态证据已相互印证：{statement}"
        if conclusion is ConclusionStatus.SUPPORTED_HYPOTHESIS and statement:
            return f"当前最佳根因假设：{statement}"
        return "现有证据不足以形成可靠根因结论。"

    def _usage_summary(self, state: InvestigationState) -> UsageSummary:
        """仅聚合 Provider 明确返回的用量，未知字段保持未知。"""

        records = state.get("usage_records", ())
        input_tokens = self._sum_optional(
            tuple(item.input_tokens for item in records)
        )
        output_tokens = self._sum_optional(
            tuple(item.output_tokens for item in records)
        )
        currencies = {
            item.currency
            for item in records
            if item.estimated_cost is not None and item.currency is not None
        }
        all_costs_known = bool(records) and all(
            item.estimated_cost is not None for item in records
        )
        estimated_cost = (
            sum(
                (item.estimated_cost for item in records if item.estimated_cost is not None),
                start=Decimal(0),
            )
            if all_costs_known and len(currencies) == 1
            else None
        )
        return UsageSummary(
            calls=len(records) or state.get("provider_call_count", 0),
            duration_ms=sum(item.duration_ms for item in records),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=estimated_cost,
            currency=next(iter(currencies)) if estimated_cost is not None else None,
        )

    def _sum_optional(self, values: tuple[int | None, ...]) -> int | None:
        """任一调用缺失精确 Token 时不伪造总数。"""

        if not values or any(value is None for value in values):
            return None
        return sum(value for value in values if value is not None)
