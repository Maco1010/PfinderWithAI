"""统一应用循环、预算和终止条件的决策节点。"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from pfinder_ai.domain.enums import ExecutionStatus, NextAction, VerificationStatus
from pfinder_ai.domain.models import InvestigationStep
from pfinder_ai.graph.nodes.common import make_step_id, next_hop_id
from pfinder_ai.graph.policy import GraphExecutionPolicy
from pfinder_ai.graph.state import InvestigationState


def _utc_now() -> datetime:
    """返回便于测试替换的当前 UTC 时间。"""

    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class DecisionRouterNode:
    """在所有循环入口前应用同一组继续调查规则。"""

    policy: GraphExecutionPolicy
    clock: Callable[[], datetime] = _utc_now

    def __call__(self, state: InvestigationState) -> InvestigationState:
        """保留 Verifier 的动作，或因验证通过、预算和无路径而终止。"""

        verification = state.get("verification")
        action = state.get("next_action") or NextAction.FINISH
        termination_reason: str | None = None

        if state.get("execution_status", ExecutionStatus.RUNNING) is not ExecutionStatus.RUNNING:
            action = NextAction.FINISH
            termination_reason = state.get("termination_reason") or "调查流程已停止"
        elif (
            verification is not None
            and verification.status is VerificationStatus.PASSED
        ):
            action = NextAction.FINISH
            termination_reason = "根因候选已通过静态假设验证"
        elif limit_reason := self._limit_reason(state):
            action = NextAction.FINISH
            termination_reason = limit_reason
        else:
            action, termination_reason = self._ensure_executable_action(state, action)

        step = InvestigationStep(
            step_id=make_step_id(state, "decision_router"),
            name="decision_router",
            target_system=(
                state["current_target"].system
                if state.get("current_target") is not None
                else None
            ),
            decision=termination_reason or f"继续执行动作 {action.value}",
            next_action=action,
        )
        return {
            "next_action": action,
            "termination_reason": termination_reason,
            "investigation_steps": (step,),
        }

    def _limit_reason(self, state: InvestigationState) -> str | None:
        """检查深度、调用次数、经过时间及已知模型用量。"""

        if state.get("investigation_depth", 0) >= self.policy.max_depth:
            return "达到最大调查深度"
        if state.get("provider_call_count", 0) >= self.policy.max_provider_calls:
            return "达到最大 Provider 调用次数"

        started_at = state.get("started_at")
        if started_at is not None and self.policy.max_elapsed_seconds is not None:
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=UTC)
            if (self.clock() - started_at).total_seconds() >= self.policy.max_elapsed_seconds:
                return "达到最大调查时间"

        usage = state.get("usage_records", ())
        input_tokens = sum(item.input_tokens or 0 for item in usage)
        output_tokens = sum(item.output_tokens or 0 for item in usage)
        if (
            self.policy.max_input_tokens is not None
            and input_tokens >= self.policy.max_input_tokens
        ):
            return "达到最大输入 Token 预算"
        if (
            self.policy.max_output_tokens is not None
            and output_tokens >= self.policy.max_output_tokens
        ):
            return "达到最大输出 Token 预算"

        if self._known_cost(state) >= (self.policy.max_estimated_cost or Decimal("Infinity")):
            return "达到最大模型成本预算"
        return None

    def _known_cost(self, state: InvestigationState) -> Decimal:
        """只累计币种与策略一致的已知成本，不猜测缺失价格。"""

        if self.policy.max_estimated_cost is None:
            return Decimal(0)
        return sum(
            (
                item.estimated_cost
                for item in state.get("usage_records", ())
                if item.estimated_cost is not None
                and item.currency == self.policy.cost_currency
            ),
            start=Decimal(0),
        )

    def _ensure_executable_action(
        self,
        state: InvestigationState,
        action: NextAction,
    ) -> tuple[NextAction, str | None]:
        """避免路由到不存在的候选或重复登记的 NextHop。"""

        visited = set(state.get("visited_target_ids", ()))
        has_target = any(
            target.target_id not in visited
            for target in state.get("target_queue", ())
        )
        enqueued = set(state.get("enqueued_next_hop_ids", ()))
        has_next_hop = any(
            next_hop_id(item) not in enqueued
            for item in state.get("next_hops", ())
        )

        if action is NextAction.SELECT_TRACE_CANDIDATE and not has_target:
            if has_next_hop:
                return NextAction.INVESTIGATE_DISCOVERED_DEPENDENCY, None
            return NextAction.FINISH, "没有尚未调查的候选目标"
        if action is NextAction.INVESTIGATE_DISCOVERED_DEPENDENCY and not has_next_hop:
            if has_target:
                return NextAction.SELECT_TRACE_CANDIDATE, None
            return NextAction.FINISH, "没有尚未登记的新依赖"
        if action is NextAction.FINISH:
            return action, "没有可执行的后续调查路径"
        return action, None
