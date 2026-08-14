"""动态运行时验证能力的预留接口。"""

from dataclasses import dataclass
from typing import Protocol

from pfinder_ai.domain.models import Evidence, Hypothesis, VerificationResult


@dataclass(frozen=True, slots=True)
class RuntimeVerificationRequest:
    """未来进行流量回放或测试环境复现所需的输入。"""

    hypothesis: Hypothesis
    evidence: tuple[Evidence, ...]


class RuntimeVerifier(Protocol):
    """第一版只声明，不提供会执行动态操作的实现。"""

    @property
    def available(self) -> bool:
        """说明当前环境是否配置了运行时验证能力。"""

        ...

    async def verify(self, request: RuntimeVerificationRequest) -> VerificationResult:
        """执行动态验证；未配置时必须显式报告不可用。"""

        ...

