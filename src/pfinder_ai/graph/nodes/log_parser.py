"""执行受限日志查询并把结果转换为安全证据。"""

from dataclasses import dataclass

from pfinder_ai.domain.enums import ErrorKind, EvidenceSource, NextAction
from pfinder_ai.domain.errors import InvalidInvestigationInputError, PfinderAIError, ProviderError
from pfinder_ai.domain.models import Evidence, InvestigationStep
from pfinder_ai.graph.nodes.common import make_error_record, make_step_id
from pfinder_ai.graph.state import InvestigationState
from pfinder_ai.ports.logs import LogProvider, LogQuery


@dataclass(frozen=True, slots=True)
class LogParserNode:
    """控制查询范围，并拒绝未脱敏或来源类型错误的日志证据。"""

    logs: LogProvider
    max_entries: int = 200

    async def __call__(self, state: InvestigationState) -> InvestigationState:
        """查询当前目标日志，失败时保留可观察错误并切换候选。"""

        target = state.get("current_target")
        context = state.get("current_context")
        call_count = state.get("provider_call_count", 0)
        error: PfinderAIError | None = None
        evidence: tuple[Evidence, ...] = ()

        if target is None or context is None:
            error = InvalidInvestigationInputError(
                "日志查询缺少当前调查目标或系统上下文"
            )
        else:
            call_count += 1
            hints = tuple(
                hint
                for request in state.get("pending_requests", ())
                if request.action is NextAction.GATHER_LOGS
                for hint in request.search_hints
            )
            try:
                evidence = await self.logs.query(
                    LogQuery(
                        incident=state["incident"],
                        target=target,
                        system_context=context,
                        trace_id=target.trace_id or state["incident"].trace_id,
                        span_id=target.span_id,
                        time_range=state["incident"].time_range,
                        search_hints=hints,
                        max_entries=self.max_entries,
                    )
                )
                self._validate_evidence(evidence)
            except PfinderAIError as caught:
                error = caught
                evidence = ()

        step = InvestigationStep(
            step_id=make_step_id(state, "log_parser"),
            name="log_parser",
            target_system=target.system if target is not None else None,
            query_summary="按系统、时间范围、业务标识和 Trace 上下文查询日志",
            evidence_ids=tuple(item.evidence_id for item in evidence),
            decision=(
                f"收集到 {len(evidence)} 条脱敏日志证据"
                if error is None
                else "日志查询失败，交由流程选择降级路径"
            ),
            next_action=(
                NextAction.INVESTIGATE_CODE
                if error is None
                else NextAction.SELECT_TRACE_CANDIDATE
            ),
        )
        update: InvestigationState = {
            "provider_call_count": call_count,
            "evidence": evidence,
            "pending_requests": tuple(
                request
                for request in state.get("pending_requests", ())
                if request.action is not NextAction.GATHER_LOGS
            ),
            "next_action": (
                NextAction.INVESTIGATE_CODE
                if error is None
                else NextAction.SELECT_TRACE_CANDIDATE
            ),
            "investigation_steps": (step,),
        }
        if error is not None:
            update["errors"] = (make_error_record(state, "log_parser", error),)
        return update

    def _validate_evidence(self, evidence: tuple[Evidence, ...]) -> None:
        """阻止不满足日志证据契约的数据进入图状态。"""

        if any(item.source is not EvidenceSource.LOG for item in evidence):
            raise ProviderError(
                "日志 Provider 返回了错误的证据来源类型",
                kind=ErrorKind.INVALID_RESPONSE,
                retryable=False,
            )
        if any(not item.redacted for item in evidence):
            raise ProviderError(
                "日志 Provider 返回了未脱敏证据",
                kind=ErrorKind.INVALID_RESPONSE,
                retryable=False,
            )
