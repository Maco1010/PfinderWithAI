"""从有序队列中选择下一个尚未调查的目标。"""

from pfinder_ai.domain.enums import NextAction
from pfinder_ai.domain.models import InvestigationStep
from pfinder_ai.graph.nodes.common import make_step_id
from pfinder_ai.graph.state import InvestigationState


class TargetSelectorNode:
    """只切换候选目标，不把候选系统误判为根因系统。"""

    def __call__(self, state: InvestigationState) -> InvestigationState:
        """按优先级选取未访问目标，并更新循环检测信息。"""

        visited = set(state.get("visited_target_ids", ()))
        available = sorted(
            (
                target
                for target in state.get("target_queue", ())
                if target.target_id not in visited
            ),
            key=lambda target: target.priority,
        )
        target = available[0] if available else None
        step = InvestigationStep(
            step_id=make_step_id(state, "select_target"),
            name="select_target",
            target_system=target.system if target is not None else None,
            decision=(
                f"选择候选目标 {target.system}"
                if target is not None
                else "没有尚未调查的候选目标"
            ),
        )

        if target is None:
            return {
                "current_target": None,
                "next_action": NextAction.FINISH,
                "termination_reason": (
                    state.get("termination_reason")
                    or "没有尚未调查的候选目标"
                ),
                "investigation_steps": (step,),
            }

        return {
            "current_target": target,
            "current_context": None,
            "current_hypothesis": None,
            "verification": None,
            "pending_requests": (),
            "visited_target_ids": (target.target_id,),
            "visited_systems": (target.system,),
            "investigation_depth": state.get("investigation_depth", 0) + 1,
            "next_action": None,
            "termination_reason": None,
            "investigation_steps": (step,),
        }
