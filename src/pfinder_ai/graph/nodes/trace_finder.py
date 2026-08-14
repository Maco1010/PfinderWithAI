"""定位候选 Trace，并在无结果时建立降级入口。"""

from dataclasses import dataclass

from pfinder_ai.domain.enums import TargetSource
from pfinder_ai.domain.errors import PfinderAIError
from pfinder_ai.domain.models import InvestigationStep, InvestigationTarget
from pfinder_ai.graph.nodes.common import make_error_record, make_step_id
from pfinder_ai.graph.state import InvestigationState
from pfinder_ai.ports.trace import TraceProvider, TraceQuery


@dataclass(frozen=True, slots=True)
class TraceFinderNode:
    """通过 TraceProvider 查找候选，不在此节点判断根因。"""

    traces: TraceProvider
    candidate_limit: int = 5

    async def __call__(self, state: InvestigationState) -> InvestigationState:
        """查询候选 Trace；查询失败或无结果时退回起始系统。"""

        incident = state["incident"]
        start_context = state["start_context"]
        call_count = state.get("provider_call_count", 0) + 1
        error: PfinderAIError | None = None
        try:
            candidates = await self.traces.find_candidates(
                TraceQuery(
                    incident=incident,
                    start_context=start_context,
                    limit=self.candidate_limit,
                )
            )
        except PfinderAIError as caught:
            candidates = ()
            error = caught

        fallback_targets: tuple[InvestigationTarget, ...] = ()
        if not candidates:
            fallback_targets = (
                InvestigationTarget(
                    target_id=f"start:{start_context.system.casefold()}",
                    system=start_context.system,
                    source=TargetSource.START_SYSTEM,
                    reason="未找到候选 Trace，从起始系统日志和代码降级调查",
                    priority=0,
                    trace_id=incident.trace_id,
                ),
            )

        decision = (
            f"找到 {len(candidates)} 个候选 Trace"
            if candidates
            else "未找到候选 Trace，进入逐系统降级调查"
        )
        step = InvestigationStep(
            step_id=make_step_id(state, "trace_finder"),
            name="trace_finder",
            target_system=start_context.system,
            query_summary="按 TraceID 或业务标识与时间范围查询候选 Trace",
            decision=decision,
        )
        update: InvestigationState = {
            "provider_call_count": call_count,
            "trace_candidates": candidates,
            "target_queue": fallback_targets,
            "investigation_steps": (step,),
        }
        if error is not None:
            update["errors"] = (make_error_record(state, "trace_finder", error),)
        return update
