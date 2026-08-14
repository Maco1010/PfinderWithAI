"""把 Trace 外新发现的依赖加入候选队列。"""

from pfinder_ai.domain.enums import NextAction, TargetSource
from pfinder_ai.domain.models import InvestigationStep, InvestigationTarget
from pfinder_ai.graph.nodes.common import make_step_id, next_hop_id
from pfinder_ai.graph.state import InvestigationState


class EnqueueNextHopsNode:
    """只登记真正的新依赖，不用于普通 Trace 候选切换。"""

    def __call__(self, state: InvestigationState) -> InvestigationState:
        """为未登记依赖生成稳定目标，并维持现有候选顺序。"""

        enqueued = set(state.get("enqueued_next_hop_ids", ()))
        pending = [
            item
            for item in state.get("next_hops", ())
            if next_hop_id(item) not in enqueued
        ]
        existing_priorities = [
            item.priority for item in state.get("target_queue", ())
        ]
        next_priority = max(existing_priorities, default=-1) + 1
        targets = tuple(
            InvestigationTarget(
                target_id=f"next-hop:{next_hop_id(item)}",
                system=item.target_system,
                source=TargetSource.DISCOVERED_DEPENDENCY,
                reason=item.reason,
                priority=next_priority + index,
                operation=item.search_context.get("operation"),
            )
            for index, item in enumerate(pending)
        )
        ids = tuple(next_hop_id(item) for item in pending)
        step = InvestigationStep(
            step_id=make_step_id(state, "enqueue_next_hops"),
            name="enqueue_next_hops",
            decision=f"登记 {len(targets)} 个 Trace 外新依赖",
            next_action=NextAction.SELECT_TRACE_CANDIDATE,
        )
        return {
            "target_queue": targets,
            "enqueued_next_hop_ids": ids,
            "next_action": NextAction.SELECT_TRACE_CANDIDATE,
            "investigation_steps": (step,),
        }
