"""调查流程条件路由测试。"""

from pfinder_ai.domain.enums import ExecutionStatus, NextAction, TargetSource
from pfinder_ai.domain.models import IncidentInput, InvestigationTarget, SystemContext
from pfinder_ai.graph.routing import (
    route_after_clue_extraction,
    route_after_decision,
    route_after_start_context,
    route_after_target_selection,
)
from pfinder_ai.graph.state import InvestigationState


def _base_state() -> InvestigationState:
    """创建只包含图必需输入的合成状态。"""

    return InvestigationState(
        investigation_id="investigation-1",
        incident=IncidentInput(
            description="下单失败",
            start_system="system-a",
        ),
        execution_status=ExecutionStatus.RUNNING,
    )


def test_incomplete_input_routes_to_result_builder() -> None:
    """缺少起始系统时必须等待输入，不能继续调用数据源。"""

    state = _base_state()
    state["incident"] = IncidentInput(
        description="下单失败",
        missing_fields=("start_system",),
    )

    assert route_after_clue_extraction(state) == "build_result"


def test_context_and_target_routes_require_resolved_values() -> None:
    """系统上下文和当前目标均已确定时才能进入证据采集。"""

    state = _base_state()
    assert route_after_start_context(state) == "build_result"
    assert route_after_target_selection(state) == "build_result"

    state["start_context"] = SystemContext(system="system-a")
    state["current_target"] = InvestigationTarget(
        target_id="trace-1:span-2",
        system="system-b",
        source=TargetSource.TRACE_CANDIDATE,
        reason="显式错误",
        priority=0,
    )

    assert route_after_start_context(state) == "find_trace"
    assert route_after_target_selection(state) == "resolve_target_context"


def test_decision_route_respects_action_and_termination() -> None:
    """结构化下一动作只有在流程仍可继续时才生效。"""

    state = _base_state()
    state["next_action"] = NextAction.GATHER_LOGS
    assert route_after_decision(state) == "gather_logs"

    state["termination_reason"] = "达到最大调查深度"
    assert route_after_decision(state) == "build_result"
