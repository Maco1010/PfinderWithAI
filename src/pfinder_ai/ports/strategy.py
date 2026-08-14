"""版本化调查策略的加载接口。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class InvestigationStrategy:
    """随应用发布、不可在运行时自行修改的调查策略。"""

    name: str
    version: str
    instructions: tuple[str, ...]


class InvestigationStrategyProvider(Protocol):
    """加载配置指定的已发布策略版本。"""

    def load(self, version: str | None = None) -> InvestigationStrategy:
        """返回固定策略；未知版本必须显式失败。"""

        ...

