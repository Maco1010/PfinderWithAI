"""在受控临时仓库中委派代码调查子 Agent。"""

from dataclasses import dataclass

from pfinder_ai.domain.enums import ErrorKind, EvidenceSource, NextAction
from pfinder_ai.domain.errors import InvalidInvestigationInputError, PfinderAIError, ProviderError
from pfinder_ai.domain.models import InvestigationStep
from pfinder_ai.graph.nodes.common import make_error_record, make_step_id
from pfinder_ai.graph.state import InvestigationState
from pfinder_ai.ports.code_analysis import (
    CodeAnalysisProvider,
    CodeInvestigationRequest,
    CodeInvestigationResult,
)
from pfinder_ai.services.workspace_manager import GitWorkspaceManager


@dataclass(frozen=True, slots=True)
class CodeInvestigatorNode:
    """协调工作区生命周期，并只接收结构化代码调查结果。"""

    code_analysis: CodeAnalysisProvider
    workspaces: GitWorkspaceManager

    async def __call__(self, state: InvestigationState) -> InvestigationState:
        """调查当前目标代码；无论成功失败都由 Manager 清理临时仓库。"""

        target = state.get("current_target")
        context = state.get("current_context")
        call_count = state.get("provider_call_count", 0)
        error: PfinderAIError | None = None
        result = CodeInvestigationResult()

        if target is None or context is None:
            error = InvalidInvestigationInputError(
                "代码调查缺少当前目标或系统上下文"
            )
        else:
            call_count += 1
            search_hints = tuple(
                hint
                for request in state.get("pending_requests", ())
                if request.action is NextAction.INVESTIGATE_CODE
                for hint in request.search_hints
            )
            relevant_evidence = tuple(
                item
                for item in state.get("evidence", ())
                if item.source is EvidenceSource.TRACE
                or item.system in {None, target.system}
            )
            try:
                async with self.workspaces.prepare(context) as workspace:
                    result = await self.code_analysis.investigate(
                        CodeInvestigationRequest(
                            incident=state["incident"],
                            target=target,
                            workspace=workspace,
                            trace_and_log_evidence=relevant_evidence,
                            search_hints=search_hints,
                        )
                    )
                self._validate_result(result)
            except PfinderAIError as caught:
                error = caught
                result = CodeInvestigationResult()

        hypothesis = (
            max(result.hypotheses, key=lambda item: item.confidence)
            if result.hypotheses
            else None
        )
        decision = (
            f"生成 {len(result.hypotheses)} 个根因候选"
            if error is None
            else "代码调查失败，交由流程选择降级路径"
        )
        if result.partial:
            decision += "；结果因预算或超时而不完整"
        step = InvestigationStep(
            step_id=make_step_id(state, "code_investigator"),
            name="code_investigator",
            target_system=target.system if target is not None else None,
            query_summary="在受控只读工作区内追踪相关代码路径",
            evidence_ids=tuple(item.evidence_id for item in result.evidence),
            decision=decision,
            confidence=hypothesis.confidence if hypothesis is not None else None,
            next_action=(
                None if error is None else NextAction.SELECT_TRACE_CANDIDATE
            ),
        )
        update: InvestigationState = {
            "provider_call_count": call_count,
            "evidence": result.evidence,
            "hypotheses": result.hypotheses,
            "current_hypothesis": hypothesis,
            "supplemental_requests": result.supplemental_requests,
            "pending_requests": result.supplemental_requests,
            "next_hops": result.discovered_dependencies,
            "unresolved_questions": result.unresolved_questions,
            "next_action": (
                None if error is None else NextAction.SELECT_TRACE_CANDIDATE
            ),
            "investigation_steps": (step,),
        }
        if error is not None:
            update["errors"] = (
                make_error_record(state, "code_investigator", error),
            )
        return update

    def _validate_result(self, result: CodeInvestigationResult) -> None:
        """拒绝供应商类型泄漏和未脱敏代码证据。"""

        if any(item.source is not EvidenceSource.CODE for item in result.evidence):
            raise ProviderError(
                "CodeAnalysisProvider 返回了错误的证据来源类型",
                kind=ErrorKind.INVALID_RESPONSE,
                retryable=False,
            )
        if any(not item.redacted for item in result.evidence):
            raise ProviderError(
                "CodeAnalysisProvider 返回了未脱敏证据",
                kind=ErrorKind.INVALID_RESPONSE,
                retryable=False,
            )
