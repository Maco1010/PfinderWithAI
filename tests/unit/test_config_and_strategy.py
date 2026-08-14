"""配置边界和固定调查策略测试。"""

import pytest
from pydantic import ValidationError

from pfinder_ai.config import AppSettings
from pfinder_ai.strategies import DefaultInvestigationStrategyProvider


def test_settings_reject_unbounded_or_zero_limits() -> None:
    """Demo 默认值可覆盖，但调查边界不能失效。"""

    with pytest.raises(ValidationError):
        AppSettings(max_depth=0)


def test_default_strategy_is_versioned_and_immutable() -> None:
    """策略必须通过稳定版本加载，未知版本不能静默回退。"""

    provider = DefaultInvestigationStrategyProvider()

    assert provider.load().version == "v1"
    with pytest.raises(ValueError, match="未知调查策略版本"):
        provider.load("v2")
