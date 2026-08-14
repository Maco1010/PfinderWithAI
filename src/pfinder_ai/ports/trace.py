"""跨系统 Trace 数据源接口。"""

from dataclasses import dataclass
from typing import Protocol

from pfinder_ai.domain.models import IncidentInput, SystemContext, TraceCandidate


@dataclass(frozen=True, slots=True)
class TraceQuery:
    """定位候选 Trace 所需的最小查询条件。"""

    incident: IncidentInput
    start_context: SystemContext
    limit: int = 5


class TraceProvider(Protocol):
    """获取 Provider 中立的候选 Trace。"""

    async def find_candidates(self, query: TraceQuery) -> tuple[TraceCandidate, ...]:
        """返回按数据源相关度排序的候选 Trace。"""

        ...

