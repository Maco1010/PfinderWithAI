"""可以安全跨越应用边界传递的结构化异常。"""

from collections.abc import Mapping
from typing import Any

from pfinder_ai.domain.enums import ErrorKind


class PfinderAIError(Exception):
    """包含重试语义和非敏感上下文的基础异常。

    Adapter 应将供应商异常转换为该异常体系。``context`` 只能保存标识符
    或摘要，禁止附加原始日志、访问凭证和客户数据。
    """

    def __init__(
        self,
        message: str,
        *,
        kind: ErrorKind,
        retryable: bool = False,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.context = dict(context or {})


class InvalidInvestigationInputError(PfinderAIError):
    """缺少必要输入或输入相互矛盾时抛出。"""

    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            message,
            kind=ErrorKind.INVALID_INPUT,
            retryable=False,
            context=context,
        )


class ProviderError(PfinderAIError):
    """外部 Provider Adapter 返回的标准化异常。"""


class StructuredOutputError(PfinderAIError):
    """模型结果无法解析为声明的结构时抛出。"""

    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            message,
            kind=ErrorKind.INVALID_RESPONSE,
            retryable=True,
            context=context,
        )


class BudgetExceededError(PfinderAIError):
    """调查达到配置的执行预算时抛出。"""

    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            message,
            kind=ErrorKind.BUDGET_EXCEEDED,
            retryable=False,
            context=context,
        )
