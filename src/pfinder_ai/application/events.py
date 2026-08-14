"""应用层向交互入口发布的非敏感进度事件。"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol


class EventKind(StrEnum):
    """CLI 和未来 HTTP 流式接口共享的事件类型。"""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class InvestigationEvent:
    """不包含原始日志、代码和凭证的调查进度事件。"""

    investigation_id: str
    kind: EventKind
    message: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class InvestigationEventSink(Protocol):
    """隔离控制台、HTTP 流和未来消息系统。"""

    async def emit(self, event: InvestigationEvent) -> None:
        """发布一个非敏感进度事件。"""

        ...


class NullInvestigationEventSink:
    """不需要实时进度时使用的空实现。"""

    async def emit(self, event: InvestigationEvent) -> None:
        """显式忽略事件，不影响主调查流程。"""

        del event
