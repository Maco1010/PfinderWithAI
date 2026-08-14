"""把最终结果写入独立调查轨迹存储。"""

from dataclasses import dataclass

from pfinder_ai.domain.enums import ExecutionStatus, NextAction
from pfinder_ai.domain.errors import PfinderAIError
from pfinder_ai.domain.models import InvestigationStep
from pfinder_ai.graph.nodes.common import make_error_record, make_step_id
from pfinder_ai.graph.state import InvestigationState, merge_steps
from pfinder_ai.ports.stores import InvestigationStore


@dataclass(frozen=True, slots=True)
class ResultPersisterNode:
    """保存审计结果；LangGraph Checkpointer 仍独立负责流程恢复。"""

    store: InvestigationStore

    async def __call__(self, state: InvestigationState) -> InvestigationState:
        """持久化最终结果，并显式暴露存储失败。"""

        result = state["result"]
        if result is None:
            raise ValueError("持久化结果前必须先执行 ResultBuilder")

        step = InvestigationStep(
            step_id=make_step_id(state, "persist_result"),
            name="persist_result",
            decision="保存最终诊断结果和终止原因",
            next_action=NextAction.FINISH,
        )
        enriched_result = result.model_copy(
            update={
                "investigation_steps": merge_steps(
                    result.investigation_steps,
                    (step,),
                )
            }
        )
        call_count = state.get("provider_call_count", 0) + 1
        try:
            await self.store.save_result(
                state["investigation_id"],
                enriched_result,
            )
        except PfinderAIError as error:
            reason = "诊断已经生成，但最终结果持久化失败"
            failed_result = enriched_result.model_copy(
                update={
                    "execution_status": ExecutionStatus.FAILED,
                    "termination_reason": reason,
                }
            )
            return {
                "provider_call_count": call_count,
                "execution_status": ExecutionStatus.FAILED,
                "termination_reason": reason,
                "errors": (make_error_record(state, "persist_result", error),),
                "investigation_steps": (step,),
                "result": failed_result,
            }

        return {
            "provider_call_count": call_count,
            "investigation_steps": (step,),
            "result": enriched_result,
        }
