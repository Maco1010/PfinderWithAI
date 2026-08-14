"""UsageMonitor 的成功、失败和未知用量语义测试。"""

import asyncio
from decimal import Decimal

import pytest

from pfinder_ai.monitoring import UsageMonitor


class StepClock:
    """每次调用推进固定时间的测试时钟。"""

    def __init__(self, *values: float) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        """返回下一个预设时间点。"""

        return next(self._values)


def test_monitor_records_explicit_model_usage() -> None:
    """供应商返回的 Token 和成本应按原值进入汇总。"""

    async def run_case() -> UsageMonitor:
        monitor = UsageMonitor(clock=StepClock(1.0, 1.25))
        async with monitor.track(
            provider="fake-llm",
            operation="extract-clues",
        ) as measurement:
            measurement.set_model_usage(
                input_tokens=100,
                output_tokens=20,
                estimated_cost=Decimal("0.01"),
                currency="USD",
            )
        return monitor

    monitor = asyncio.run(run_case())
    record = monitor.snapshot()[0]
    summary = monitor.summarize()

    assert record.success is True
    assert record.duration_ms == 250
    assert summary.input_tokens == 100
    assert summary.estimated_cost == Decimal("0.01")


def test_monitor_records_failure_without_swallowing_exception() -> None:
    """调用异常仍写入失败记录，并继续向调用方抛出。"""

    async def run_case(monitor: UsageMonitor) -> None:
        async with monitor.track(provider="fake-log", operation="query"):
            raise RuntimeError("synthetic failure")

    monitor = UsageMonitor(clock=StepClock(2.0, 2.1))
    with pytest.raises(RuntimeError, match="synthetic failure"):
        asyncio.run(run_case(monitor))

    assert monitor.snapshot()[0].success is False


def test_unknown_usage_is_not_guessed() -> None:
    """缺少 Token 或成本信息时，汇总字段必须保持未知。"""

    async def run_case() -> UsageMonitor:
        monitor = UsageMonitor(clock=StepClock(3.0, 3.1))
        async with monitor.track(provider="fake-trace", operation="find"):
            pass
        return monitor

    summary = asyncio.run(run_case()).summarize()

    assert summary.input_tokens is None
    assert summary.estimated_cost is None
