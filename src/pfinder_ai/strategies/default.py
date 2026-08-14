"""第一版固定调查策略。"""

from pfinder_ai.ports.strategy import InvestigationStrategy


class DefaultInvestigationStrategyProvider:
    """只加载随代码发布的策略，不允许运行时自行改写。"""

    _STRATEGY = InvestigationStrategy(
        name="evidence-first",
        version="v1",
        instructions=(
            "先缩小系统、时间范围和业务标识，再获取证据",
            "明确区分事实、推断和未知项",
            "根因候选必须引用 Trace、日志或代码证据",
            "优先调查 Trace 队列，只有新依赖才创建 NextHop",
            "达到深度、时间或调用预算时输出当前最佳结果",
        ),
    )

    def load(self, version: str | None = None) -> InvestigationStrategy:
        """返回唯一已发布版本，未知版本显式失败。"""

        requested = version or self._STRATEGY.version
        if requested != self._STRATEGY.version:
            raise ValueError(f"未知调查策略版本：{requested}")
        return self._STRATEGY
