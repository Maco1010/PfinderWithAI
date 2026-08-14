"""输入、Trace、目标选择与日志节点的纵向单元测试。"""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from pfinder_ai.domain.enums import (
    EvidenceSource,
    ExecutionStatus,
    TargetSource,
)
from pfinder_ai.domain.models import (
    Evidence,
    IncidentInput,
    SystemContext,
    TimeRange,
    TraceCandidate,
    TraceSpan,
)
from pfinder_ai.graph.nodes.clue_extractor import ClueExtractorNode
from pfinder_ai.graph.nodes.context_resolver import ContextResolverNode
from pfinder_ai.graph.nodes.log_parser import LogParserNode
from pfinder_ai.graph.nodes.target_selector import TargetSelectorNode
from pfinder_ai.graph.nodes.trace_analyser import TraceAnalyserNode
from pfinder_ai.graph.nodes.trace_finder import TraceFinderNode
from pfinder_ai.graph.state import InvestigationState
from pfinder_ai.ports.logs import LogQuery
from pfinder_ai.ports.metadata import SystemResolution
from pfinder_ai.ports.trace import TraceQuery
from pfinder_ai.services.trace_analysis import TraceAnalysisService


class StubLLMProvider:
    """返回预设结构化线索的通用模型替身。"""

    def __init__(self, output: IncidentInput) -> None:
        self.output = output

    @property
    def provider_name(self) -> str:
        """返回测试使用的稳定供应商名称。"""

        return "stub"

    async def generate_structured[StructuredModel: BaseModel](
        self,
        *,
        task: str,
        prompt: str,
        output_type: type[StructuredModel],
    ) -> StructuredModel:
        """把预设结果重新校验为调用方声明的模型。"""

        del task, prompt
        return output_type.model_validate(self.output.model_dump())


class StubMetadataProvider:
    """根据系统名返回合成资源上下文。"""

    async def resolve_system(self, system: str) -> SystemResolution:
        """返回不含真实内部地址的测试上下文。"""

        return SystemResolution(
            candidates=(
                SystemContext(
                    system=system,
                    repository_url=f"https://git.example.local/{system}.git",
                    revision="synthetic-revision",
                    log_source=f"synthetic-{system}",
                ),
            )
        )


class StubTraceProvider:
    """返回包含一个显式错误 Span 的合成 Trace。"""

    async def find_candidates(self, query: TraceQuery) -> tuple[TraceCandidate, ...]:
        """使用查询中的系统生成稳定候选。"""

        return (
            TraceCandidate(
                trace_id="trace-synthetic",
                match_score=0.95,
                match_reason="合成业务标识和时间范围匹配",
                spans=(
                    TraceSpan(
                        span_id="span-error",
                        system=query.start_context.system,
                        operation="create_order",
                        duration_ms=320,
                        status="error",
                        error_summary="synthetic timeout",
                    ),
                ),
            ),
        )


class StubLogProvider:
    """返回已经脱敏的合成日志证据。"""

    def __init__(self, *, redacted: bool = True) -> None:
        self.redacted = redacted

    async def query(self, query: LogQuery) -> tuple[Evidence, ...]:
        """保留可复核的合成来源定位。"""

        return (
            Evidence(
                evidence_id="log:synthetic:1",
                source=EvidenceSource.LOG,
                summary="合成订单写入超时",
                locator=f"{query.system_context.log_source}:entry-1",
                system=query.target.system,
                redacted=self.redacted,
            ),
        )


def _incident() -> IncidentInput:
    """创建具备必要查询范围的合成问题输入。"""

    now = datetime.now(UTC)
    return IncidentInput(
        description="合成下单失败",
        business_keys={"order_id": "synthetic-001"},
        start_system="system-a",
        time_range=TimeRange(
            start=now - timedelta(minutes=5),
            end=now,
        ),
    )


def test_clue_extractor_preserves_explicit_fields() -> None:
    """模型补全结果不能覆盖用户显式提供的系统和业务标识。"""

    provided = _incident()
    model_output = IncidentInput(
        description="模型改写描述",
        business_keys={"model_key": "model-value"},
        start_system="model-system",
        trace_id="trace-from-model",
    )
    node = ClueExtractorNode(StubLLMProvider(model_output))

    update = asyncio.run(
        node(
            InvestigationState(
                investigation_id="investigation-1",
                incident=provided,
            )
        )
    )
    incident = update["incident"]

    assert incident.start_system == "system-a"
    assert incident.business_keys["order_id"] == "synthetic-001"
    assert incident.trace_id == "trace-from-model"
    assert incident.missing_fields == ()
    assert update["execution_status"] is ExecutionStatus.RUNNING


def test_trace_nodes_create_trace_linked_target() -> None:
    """Trace 查询和分析后，目标必须携带 TraceID 与 SpanID。"""

    incident = _incident()
    context = SystemContext(system="system-a")
    finder_update = asyncio.run(
        TraceFinderNode(StubTraceProvider())(
            InvestigationState(
                investigation_id="investigation-1",
                incident=incident,
                start_context=context,
            )
        )
    )
    analyser_update = TraceAnalyserNode(TraceAnalysisService())(
        InvestigationState(
            investigation_id="investigation-1",
            incident=incident,
            trace_candidates=finder_update["trace_candidates"],
        )
    )
    target = analyser_update["target_queue"][0]

    assert target.source is TargetSource.TRACE_CANDIDATE
    assert target.trace_id == "trace-synthetic"
    assert target.span_id == "span-error"


def test_context_selection_and_log_collection() -> None:
    """目标系统解析完成后，只允许脱敏日志证据进入状态。"""

    incident = _incident()
    trace_update = asyncio.run(
        TraceFinderNode(StubTraceProvider())(
            InvestigationState(
                investigation_id="investigation-1",
                incident=incident,
                start_context=SystemContext(system="system-a"),
            )
        )
    )
    analysed = TraceAnalyserNode(TraceAnalysisService())(
        InvestigationState(
            investigation_id="investigation-1",
            incident=incident,
            trace_candidates=trace_update["trace_candidates"],
        )
    )
    selected = TargetSelectorNode()(
        InvestigationState(
            investigation_id="investigation-1",
            incident=incident,
            target_queue=analysed["target_queue"],
        )
    )
    target = selected["current_target"]
    assert target is not None

    context_update = asyncio.run(
        ContextResolverNode(StubMetadataProvider()).resolve_target(
            InvestigationState(
                investigation_id="investigation-1",
                incident=incident,
                current_target=target,
            )
        )
    )
    context = context_update["current_context"]
    assert context is not None

    log_update = asyncio.run(
        LogParserNode(StubLogProvider())(
            InvestigationState(
                investigation_id="investigation-1",
                incident=incident,
                current_target=target,
                current_context=context,
            )
        )
    )

    assert log_update["evidence"][0].source is EvidenceSource.LOG
    assert log_update["evidence"][0].redacted is True


def test_log_node_rejects_unredacted_evidence() -> None:
    """Adapter 违反脱敏契约时，节点记录错误且不保存证据。"""

    incident = _incident()
    target = TraceAnalyserNode(TraceAnalysisService())(
        InvestigationState(
            investigation_id="investigation-1",
            incident=incident,
            trace_candidates=asyncio.run(
                StubTraceProvider().find_candidates(
                    TraceQuery(
                        incident=incident,
                        start_context=SystemContext(system="system-a"),
                    )
                )
            ),
        )
    )["target_queue"][0]
    update = asyncio.run(
        LogParserNode(StubLogProvider(redacted=False))(
            InvestigationState(
                investigation_id="investigation-1",
                incident=incident,
                current_target=target,
                current_context=SystemContext(
                    system="system-a",
                    log_source=str(Path("synthetic-logs")),
                ),
            )
        )
    )

    assert update["evidence"] == ()
    assert update["errors"][0].step_name == "log_parser"
