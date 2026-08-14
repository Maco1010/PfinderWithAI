"""主调查图使用的无副作用条件路由。"""

from typing import Literal

from pfinder_ai.domain.enums import ExecutionStatus, NextAction
from pfinder_ai.graph.state import InvestigationState

type InputRoute = Literal["resolve_start_context", "build_result"]
type ContextRoute = Literal["find_trace", "build_result"]
type TargetRoute = Literal["resolve_target_context", "build_result"]
type TargetContextRoute = Literal["gather_logs", "select_target", "build_result"]
type LogRoute = Literal["investigate_code", "decision_router"]
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


def route_after_target_context(state: InvestigationState) -> TargetContextRoute:
    """目标上下文解析失败时切换候选，不把错误上下文传给日志节点。"""

    if state.get("termination_reason"):
        return "build_result"
    if state.get("current_context") is not None:
        return "gather_logs"

    visited = set(state.get("visited_target_ids", ()))
    if any(
        target.target_id not in visited
        for target in state.get("target_queue", ())
    ):
        return "select_target"
    return "build_result"


def route_after_log_collection(state: InvestigationState) -> LogRoute:
    """日志失败时先进入统一决策，成功时继续调查代码。"""

    if state.get("next_action") is NextAction.SELECT_TRACE_CANDIDATE:
        return "decision_router"
    return "investigate_code"


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
