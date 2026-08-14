"""Provider 调用用量的内存采集基线。"""

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from time import perf_counter
from typing import Any

from pfinder_ai.domain.models import UsageRecord, UsageSummary


@dataclass(slots=True)
class UsageMeasurement:
    """一次调用执行期间可以补充的明确用量字段。"""

    provider: str
    operation: str
    retries: int
    details: dict[str, Any] = field(default_factory=dict)
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: Decimal | None = None
    currency: str | None = None

    def set_model_usage(
        self,
        *,
        input_tokens: int | None,
        output_tokens: int | None,
        estimated_cost: Decimal | None = None,
        currency: str | None = None,
    ) -> None:
        """保存供应商明确返回的 Token 和成本，不进行缺失值猜测。"""

        if input_tokens is not None and input_tokens < 0:
            raise ValueError("input_tokens 不能小于 0")
        if output_tokens is not None and output_tokens < 0:
            raise ValueError("output_tokens 不能小于 0")
        if estimated_cost is not None and estimated_cost < 0:
            raise ValueError("estimated_cost 不能小于 0")
        if estimated_cost is not None and not currency:
            raise ValueError("记录成本时必须同时提供币种")

        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.estimated_cost = estimated_cost
        self.currency = currency if estimated_cost is not None else None


class UsageMonitor:
    """采集用量元数据，并提供不可变快照与保守汇总。"""

    def __init__(self, *, clock: Callable[[], float] = perf_counter) -> None:
        self._clock = clock
        self._records: list[UsageRecord] = []

    @asynccontextmanager
    async def track(
        self,
        *,
        provider: str,
        operation: str,
        retries: int = 0,
        details: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[UsageMeasurement]:
        """围绕一次异步调用记录耗时和成功状态。"""

        if not provider or not operation:
            raise ValueError("provider 和 operation 不能为空")
        if retries < 0:
            raise ValueError("retries 不能小于 0")

        measurement = UsageMeasurement(
            provider=provider,
            operation=operation,
            retries=retries,
            details=dict(details or {}),
        )
        started = self._clock()
        success = False
        try:
            yield measurement
            success = True
        finally:
            duration_ms = max(0.0, (self._clock() - started) * 1000)
            self._records.append(
                UsageRecord(
                    provider=measurement.provider,
                    operation=measurement.operation,
                    duration_ms=duration_ms,
                    success=success,
                    retries=measurement.retries,
                    input_tokens=measurement.input_tokens,
                    output_tokens=measurement.output_tokens,
                    estimated_cost=measurement.estimated_cost,
                    currency=measurement.currency,
                    details=measurement.details,
                )
            )

    def snapshot(self) -> tuple[UsageRecord, ...]:
        """返回当前记录的不可变快照。"""

        return tuple(self._records)

    def summarize(self) -> UsageSummary:
        """聚合明确值；任一调用未知时，相应总量保持未知。"""

        records = self.snapshot()
        currencies = {
            item.currency
            for item in records
            if item.estimated_cost is not None and item.currency is not None
        }
        all_costs_known = bool(records) and all(
            item.estimated_cost is not None for item in records
        )
        estimated_cost = (
            sum(
                (
                    item.estimated_cost
                    for item in records
                    if item.estimated_cost is not None
                ),
                start=Decimal(0),
            )
            if all_costs_known and len(currencies) == 1
            else None
        )
        return UsageSummary(
            calls=len(records),
            duration_ms=sum(item.duration_ms for item in records),
            input_tokens=self._sum_optional(
                tuple(item.input_tokens for item in records)
            ),
            output_tokens=self._sum_optional(
                tuple(item.output_tokens for item in records)
            ),
            estimated_cost=estimated_cost,
            currency=next(iter(currencies)) if estimated_cost is not None else None,
        )

    def _sum_optional(self, values: tuple[int | None, ...]) -> int | None:
        """只在每个调用都提供精确 Token 时返回总量。"""

        if not values or any(value is None for value in values):
            return None
        return sum(value for value in values if value is not None)
