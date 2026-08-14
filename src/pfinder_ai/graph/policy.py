"""主调查图的显式执行边界。"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class GraphExecutionPolicy:
    """由配置层提供的深度、调用、时间和模型用量上限。

    这里不提供生产默认值，避免把尚未确认的预算写死在领域流程中。
    """

    max_depth: int
    max_provider_calls: int
    max_elapsed_seconds: float | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_estimated_cost: Decimal | None = None
    cost_currency: str | None = None

    def __post_init__(self) -> None:
        """拒绝会让流程无法执行或无法解释的预算配置。"""

        if self.max_depth < 1:
            raise ValueError("max_depth 必须大于 0")
        if self.max_provider_calls < 1:
            raise ValueError("max_provider_calls 必须大于 0")
        optional_limits = (
            self.max_elapsed_seconds,
            self.max_input_tokens,
            self.max_output_tokens,
            self.max_estimated_cost,
        )
        if any(limit is not None and limit <= 0 for limit in optional_limits):
            raise ValueError("可选预算上限必须大于 0")
        if self.max_estimated_cost is not None and not self.cost_currency:
            raise ValueError("配置成本上限时必须同时提供币种")
