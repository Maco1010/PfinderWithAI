"""配置边界和固定调查策略测试。"""

import pytest
from pydantic import SecretStr, ValidationError

from pfinder_ai.config import AppSettings
from pfinder_ai.strategies import DefaultInvestigationStrategyProvider


def test_settings_reject_unbounded_or_zero_limits() -> None:
    """Demo 默认值可覆盖，但调查边界不能失效。"""

    with pytest.raises(ValidationError):
        AppSettings(max_depth=0, _env_file=None)  # type: ignore[call-arg]


def test_settings_ignore_empty_optional_environment_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """示例配置中的空可选项应保持为未配置状态。"""

    monkeypatch.setenv("PFINDER_AI_CODEX_MODEL", "")
    monkeypatch.setenv("PFINDER_AI_CODEX_BIN", "")

    settings = AppSettings(_env_file=None)  # type: ignore[call-arg]

    assert settings.codex_model is None
    assert settings.codex_bin is None


def test_gateway_settings_require_complete_credentials() -> None:
    """显式启用模型网关时不得接受缺失地址、模型或凭证的配置。"""

    with pytest.raises(ValidationError, match="llm_base_url"):
        AppSettings(llm_provider="gateway", _env_file=None)  # type: ignore[call-arg]


def test_gateway_settings_require_explicit_internal_http_opt_in() -> None:
    """非本地明文 HTTP 地址必须由部署配置显式确认。"""

    with pytest.raises(ValidationError, match="llm_allow_insecure_http"):
        AppSettings(  # type: ignore[call-arg]
            llm_provider="gateway",
            llm_base_url="http://llm.example.test",
            llm_api_key=SecretStr("synthetic-secret"),
            llm_model="synthetic-model",
            _env_file=None,
        )

    settings = AppSettings(  # type: ignore[call-arg]
        llm_provider="gateway",
        llm_base_url="http://llm.example.test",
        llm_api_key=SecretStr("synthetic-secret"),
        llm_model="synthetic-model",
        llm_allow_insecure_http=True,
        _env_file=None,
    )
    assert settings.llm_provider == "gateway"
    assert "synthetic-secret" not in repr(settings)


def test_default_strategy_is_versioned_and_immutable() -> None:
    """策略必须通过稳定版本加载，未知版本不能静默回退。"""

    provider = DefaultInvestigationStrategyProvider()

    assert provider.load().version == "v1"
    with pytest.raises(ValueError, match="未知调查策略版本"):
        provider.load("v2")
