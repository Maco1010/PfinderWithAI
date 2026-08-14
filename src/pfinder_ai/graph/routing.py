"""主调查图使用的无副作用条件路由。"""

from typing import Literal

from pfinder_ai.domain.enums import ExecutionStatus, NextAction
from pfinder_ai.graph.state import InvestigationState

type InputRoute = Literal["resolve_start_context", "build_result"]
type ContextRoute = Literal["find_trace", "build_result"]
type TargetRoute = Literal["resolve_target_context", "build_result"]
type DecisionRoute = Literal[
    "gather_logs",
    "investigate_code",
    "select_target",
    "enqueue_next_hops",
    "build_result",
]


def route_after_clue_extraction(state: InvestigationState) -> InputRoute:
    """输入不完整时进入可恢复的结果构建，而不是继续猜测。"""

    incident = state["incident"]
    if incident.missing_fields or not incident.start_system:
        return "build_result"
    return "resolve_start_context"


def route_after_start_context(state: InvestigationState) -> ContextRoute:
    """只有唯一解析出起始系统上下文后才查询 Trace。"""

    if state.get("start_context") is None:
        return "build_result"
    return "find_trace"


def route_after_target_selection(state: InvestigationState) -> TargetRoute:
    """没有尚未访问的候选目标时结束当前调查。"""

    if state.get("current_target") is None:
        return "build_result"
    return "resolve_target_context"


def route_after_decision(state: InvestigationState) -> DecisionRoute:
    """把 DecisionRouter 的结构化动作映射到下一节点。"""

    if state.get("termination_reason"):
        return "build_result"

    status = state.get("execution_status", ExecutionStatus.RUNNING)
    if status is not ExecutionStatus.RUNNING:
        return "build_result"

    routes: dict[NextAction, DecisionRoute] = {
        NextAction.GATHER_LOGS: "gather_logs",
        NextAction.INVESTIGATE_CODE: "investigate_code",
        NextAction.SELECT_TRACE_CANDIDATE: "select_target",
        NextAction.INVESTIGATE_DISCOVERED_DEPENDENCY: "enqueue_next_hops",
        NextAction.FINISH: "build_result",
    }
    action = state.get("next_action")
    if action is None:
        return "build_result"
    return routes[action]
