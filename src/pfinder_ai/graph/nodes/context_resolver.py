"""把逻辑系统名解析为可访问资源上下文的节点。"""

from dataclasses import dataclass

from pfinder_ai.domain.enums import ExecutionStatus, NextAction
from pfinder_ai.domain.errors import PfinderAIError
from pfinder_ai.domain.models import InvestigationStep
from pfinder_ai.graph.nodes.common import make_error_record, make_step_id
from pfinder_ai.graph.state import InvestigationState
from pfinder_ai.ports.metadata import MetadataProvider, SystemResolution


@dataclass(frozen=True, slots=True)
class ContextResolverNode:
    """只使用 MetadataProvider 解析资源，不让 LLM 猜测内部地址。"""

    metadata: MetadataProvider

    async def resolve_start(self, state: InvestigationState) -> InvestigationState:
        """解析起始系统；无法唯一解析时等待用户或配置补充。"""

        system = state["incident"].start_system
        if system is None:
            return {
                "execution_status": ExecutionStatus.WAITING_INPUT,
                "termination_reason": "缺少起始系统",
            }

        call_count = state.get("provider_call_count", 0) + 1
        try:
            resolution = await self.metadata.resolve_system(system)
        except PfinderAIError as error:
            step = self._resolution_step(
                state,
                "resolve_start_context",
                system,
                "起始系统元数据查询失败",
            )
            return {
                "provider_call_count": call_count,
                "execution_status": ExecutionStatus.FAILED,
                "termination_reason": "起始系统元数据查询失败",
                "errors": (
                    make_error_record(state, "resolve_start_context", error),
                ),
                "investigation_steps": (step,),
            }

        if len(resolution.candidates) != 1:
            reason = self._ambiguity_reason(system, resolution)
            step = self._resolution_step(
                state,
                "resolve_start_context",
                system,
                reason,
            )
            return {
                "provider_call_count": call_count,
                "execution_status": ExecutionStatus.WAITING_INPUT,
                "termination_reason": reason,
                "unresolved_questions": (reason,),
                "investigation_steps": (step,),
            }

        context = resolution.candidates[0]
        step = self._resolution_step(
            state,
            "resolve_start_context",
            system,
            "起始系统上下文已解析",
        )
        return {
            "provider_call_count": call_count,
            "start_context": context,
            "system_contexts": {context.system.casefold(): context},
            "execution_status": ExecutionStatus.RUNNING,
            "investigation_steps": (step,),
        }

    async def resolve_target(self, state: InvestigationState) -> InvestigationState:
        """解析当前候选；失败时保留错误并允许切换其他候选。"""

        target = state.get("current_target")
        if target is None:
            return {"current_context": None}

        cached = state.get("system_contexts", {}).get(target.system.casefold())
        if cached is not None:
            return {
                "current_context": cached,
                "investigation_steps": (
                    self._resolution_step(
                        state,
                        "resolve_target_context",
                        target.system,
                        "复用已解析的系统上下文",
                    ),
                ),
            }

        call_count = state.get("provider_call_count", 0) + 1
        try:
            resolution = await self.metadata.resolve_system(target.system)
        except PfinderAIError as error:
            step = self._resolution_step(
                state,
                "resolve_target_context",
                target.system,
                "目标系统元数据查询失败，尝试其他候选",
            )
            return {
                "provider_call_count": call_count,
                "current_context": None,
                "next_action": NextAction.SELECT_TRACE_CANDIDATE,
                "errors": (
                    make_error_record(state, "resolve_target_context", error),
                ),
                "investigation_steps": (step,),
            }

        if len(resolution.candidates) != 1:
            reason = self._ambiguity_reason(target.system, resolution)
            step = self._resolution_step(
                state,
                "resolve_target_context",
                target.system,
                reason,
            )
            return {
                "provider_call_count": call_count,
                "current_context": None,
                "next_action": NextAction.SELECT_TRACE_CANDIDATE,
                "unresolved_questions": (reason,),
                "investigation_steps": (step,),
            }

        context = resolution.candidates[0]
        step = self._resolution_step(
            state,
            "resolve_target_context",
            target.system,
            "目标系统上下文已解析",
        )
        return {
            "provider_call_count": call_count,
            "current_context": context,
            "system_contexts": {context.system.casefold(): context},
            "investigation_steps": (step,),
        }

    def _ambiguity_reason(self, system: str, resolution: SystemResolution) -> str:
        """构造不包含供应商原始响应的可展示原因。"""

        if resolution.ambiguity_reason:
            return resolution.ambiguity_reason
        if not resolution.candidates:
            return f"未找到系统 {system} 的元数据"
        return f"系统 {system} 对应多个资源，无法安全地自动选择"

    def _resolution_step(
        self,
        state: InvestigationState,
        step_name: str,
        system: str,
        decision: str,
    ) -> InvestigationStep:
        """记录元数据查询决策，但不记录内部地址或凭证。"""

        return InvestigationStep(
            step_id=make_step_id(state, step_name),
            name=step_name,
            target_system=system,
            query_summary=f"解析系统 {system} 的资源上下文",
            decision=decision,
        )
