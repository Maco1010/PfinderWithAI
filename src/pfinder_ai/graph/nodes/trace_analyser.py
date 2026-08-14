"""把候选 Trace 转换为有序调查目标和可引用证据。"""

from dataclasses import dataclass

from pfinder_ai.domain.models import InvestigationStep
from pfinder_ai.graph.nodes.common import make_step_id
from pfinder_ai.graph.state import InvestigationState
from pfinder_ai.services.trace_analysis import TraceAnalysisService


@dataclass(frozen=True, slots=True)
class TraceAnalyserNode:
    """包装确定性 Trace 分析服务，后续可增加歧义处理模型。"""

    analyser: TraceAnalysisService

    def __call__(self, state: InvestigationState) -> InvestigationState:
        """生成候选队列；空 Trace 保留 TraceFinder 创建的降级目标。"""

        result = self.analyser.analyse(state.get("trace_candidates", ()))
        step = InvestigationStep(
            step_id=make_step_id(state, "trace_analyser"),
            name="trace_analyser",
            query_summary="按异常状态、错误摘要和耗时筛选关键 Span",
            evidence_ids=tuple(item.evidence_id for item in result.evidence),
            decision=f"生成 {len(result.targets)} 个 Trace 调查候选",
        )
        return {
            "target_queue": result.targets,
            "evidence": result.evidence,
            "investigation_steps": (step,),
        }
