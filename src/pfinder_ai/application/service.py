"""启动并完成一次调查的应用服务。"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from langchain_core.runnables import RunnableConfig

from pfinder_ai.application.events import (
    EventKind,
    InvestigationEvent,
    InvestigationEventSink,
    NullInvestigationEventSink,
)
from pfinder_ai.domain.enums import ErrorKind, ExecutionStatus
from pfinder_ai.domain.errors import ProviderError
from pfinder_ai.domain.models import DiagnosisResult, IncidentInput
from pfinder_ai.graph.builder import InvestigationGraph
from pfinder_ai.graph.state import InvestigationState
from pfinder_ai.ports.stores import InvestigationStore


@dataclass(slots=True)
class InvestigationApplicationService:
    """对交互层隐藏 LangGraph 配置、状态初始化和审计写入。"""

    graph: InvestigationGraph
    store: InvestigationStore
    recursion_limit: int
    event_sink: InvestigationEventSink = field(
        default_factory=NullInvestigationEventSink
    )

    async def investigate(
        self,
        incident: IncidentInput,
        *,
        investigation_id: str | None = None,
    ) -> DiagnosisResult:
        """运行一次调查，并返回已经持久化的结构化结果。"""

        identifier = investigation_id or uuid4().hex
        if not identifier.strip():
            raise ValueError("investigation_id 不能为空")

        await self.store.save_incident(identifier, incident)
        await self.event_sink.emit(
            InvestigationEvent(
                investigation_id=identifier,
                kind=EventKind.STARTED,
                message="调查任务已启动",
            )
        )
        config: RunnableConfig = {
            "configurable": {"thread_id": identifier},
            "recursion_limit": self.recursion_limit,
        }

        try:
            final_state = cast(
                InvestigationState,
                await self.graph.ainvoke(
                    InvestigationState(
                        investigation_id=identifier,
                        incident=incident,
                        investigation_depth=0,
                        provider_call_count=0,
                        started_at=datetime.now(UTC),
                        execution_status=ExecutionStatus.RUNNING,
                    ),
                    config,
                ),
            )
            result = final_state.get("result")
            if result is None:
                raise ProviderError(
                    "调查图结束但未生成 DiagnosisResult",
                    kind=ErrorKind.INTERNAL,
                    retryable=False,
                )

            for step in result.investigation_steps:
                await self.store.append_step(identifier, step)

            await self.event_sink.emit(
                InvestigationEvent(
                    investigation_id=identifier,
                    kind=EventKind.COMPLETED,
                    message="调查任务已结束",
                )
            )
            return result
        except Exception:
            await self.event_sink.emit(
                InvestigationEvent(
                    investigation_id=identifier,
                    kind=EventKind.FAILED,
                    message="调查任务执行失败",
                )
            )
            raise
