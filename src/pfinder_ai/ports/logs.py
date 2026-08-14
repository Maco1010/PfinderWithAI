"""受限、只读的日志查询接口。"""

from dataclasses import dataclass
from typing import Protocol

from pfinder_ai.domain.models import (
    Evidence,
    IncidentInput,
    InvestigationTarget,
    SystemContext,
    TimeRange,
)


@dataclass(frozen=True, slots=True)
class LogQuery:
    """一次渐进式日志检索的显式范围。"""

    incident: IncidentInput
    target: InvestigationTarget
    system_context: SystemContext
    trace_id: str | None = None
    span_id: str | None = None
    time_range: TimeRange | None = None
    search_hints: tuple[str, ...] = ()
    max_entries: int = 200


class LogProvider(Protocol):
    """查询日志并返回已经裁剪、脱敏的证据。"""

    async def query(self, query: LogQuery) -> tuple[Evidence, ...]:
        """执行只读查询，禁止返回未脱敏的原始生产日志。"""

        ...

