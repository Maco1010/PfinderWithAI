"""从用户输入提取并校验调查线索的节点。"""

from dataclasses import dataclass

from pfinder_ai.domain.enums import ExecutionStatus
from pfinder_ai.domain.errors import PfinderAIError
from pfinder_ai.domain.models import IncidentInput, InvestigationStep
from pfinder_ai.graph.nodes.common import (
    make_error_record,
    make_step_id,
    merge_text_values,
)
from pfinder_ai.graph.state import InvestigationState
from pfinder_ai.ports.llm import LLMProvider


@dataclass(frozen=True, slots=True)
class ClueExtractorNode:
    """通过通用 LLMProvider 补全语义线索，并保留显式输入优先级。"""

    llm: LLMProvider | None = None

    async def __call__(self, state: InvestigationState) -> InvestigationState:
        """提取线索；模型不可用时仍对显式 CLI 字段进行确定性校验。"""

        provided = state["incident"]
        incident = provided
        provider_call_count = state.get("provider_call_count", 0)
        error: PfinderAIError | None = None

        if self.llm is not None:
            provider_call_count += 1
            try:
                extracted = await self.llm.generate_structured(
                    task="clue_extraction",
                    prompt=self._build_prompt(provided),
                    output_type=IncidentInput,
                )
                incident = self._merge_explicit_values(extracted, provided)
            except PfinderAIError as caught:
                error = caught
                incident = provided.model_copy(
                    update={
                        "uncertainties": merge_text_values(
                            provided.uncertainties,
                            ("语义线索提取模型不可用，仅使用显式输入字段",),
                        )
                    }
                )

        missing_fields = self._find_missing_fields(incident)
        incident = incident.model_copy(update={"missing_fields": missing_fields})
        has_missing = bool(missing_fields)
        decision = (
            f"缺少必要输入：{', '.join(missing_fields)}"
            if has_missing
            else "必要调查线索已完整"
        )
        step = InvestigationStep(
            step_id=make_step_id(state, "clue_extractor"),
            name="clue_extractor",
            query_summary="提取问题线索并校验必要字段",
            decision=decision,
        )
        update: InvestigationState = {
            "incident": incident,
            "provider_call_count": provider_call_count,
            "execution_status": (
                ExecutionStatus.WAITING_INPUT
                if has_missing
                else ExecutionStatus.RUNNING
            ),
            "termination_reason": decision if has_missing else None,
            "investigation_steps": (step,),
        }
        if error is not None:
            update["errors"] = (make_error_record(state, "clue_extractor", error),)
        return update

    def _build_prompt(self, incident: IncidentInput) -> str:
        """只发送完成线索提取所需的最小结构化输入。"""

        payload = incident.model_dump_json(
            exclude={"missing_fields", "uncertainties"},
        )
        return (
            "从以下输入提取故障现象、业务标识、起始系统、TraceID 和时间范围。"
            "不得猜测仓库、日志平台或其他企业资源地址。显式字段必须原样保留。\n"
            f"输入：{payload}"
        )

    def _merge_explicit_values(
        self,
        extracted: IncidentInput,
        provided: IncidentInput,
    ) -> IncidentInput:
        """模型只补充缺失值，不能覆盖用户显式提供的字段。"""

        return extracted.model_copy(
            update={
                "description": provided.description,
                "business_keys": {
                    **extracted.business_keys,
                    **provided.business_keys,
                },
                "start_system": provided.start_system or extracted.start_system,
                "trace_id": provided.trace_id or extracted.trace_id,
                "time_range": provided.time_range or extracted.time_range,
                "uncertainties": merge_text_values(
                    extracted.uncertainties,
                    provided.uncertainties,
                ),
            }
        )

    def _find_missing_fields(self, incident: IncidentInput) -> tuple[str, ...]:
        """TraceID 缺失时要求使用业务标识和时间范围定位候选 Trace。"""

        missing: list[str] = []
        if not incident.start_system:
            missing.append("start_system")
        if not incident.trace_id:
            if not incident.business_keys:
                missing.append("business_keys")
            if incident.time_range is None:
                missing.append("time_range")
        return tuple(missing)
