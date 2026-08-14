"""企业内部系统元数据查询接口。"""

from dataclasses import dataclass
from typing import Protocol

from pfinder_ai.domain.models import SystemContext


@dataclass(frozen=True, slots=True)
class SystemResolution:
    """系统名称解析结果，允许明确表达歧义或无结果。"""

    candidates: tuple[SystemContext, ...]
    ambiguity_reason: str | None = None


class MetadataProvider(Protocol):
    """将业务系统名称解析为确定性的资源定位信息。"""

    async def resolve_system(self, system: str) -> SystemResolution:
        """返回候选上下文；无法唯一解析时不得静默选择。"""

        ...

