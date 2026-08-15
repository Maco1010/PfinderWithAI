"""从环境变量加载应用配置，并隐藏其中的敏感值。"""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """本地 Demo 配置；敏感值只从环境加载并使用 SecretStr 隐藏。"""

    model_config = SettingsConfigDict(
        env_prefix="PFINDER_AI_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    runtime_mode: Literal["fake"] = "fake"
    database_path: Path = Path(".pfinder/investigations.sqlite3")
    workspace_base_directory: Path = Path(".pfinder/workspaces")
    trusted_git_hosts: tuple[str, ...] = ("git.example.local",)

    max_depth: int = Field(default=4, ge=1)
    max_provider_calls: int = Field(default=20, ge=1)
    max_elapsed_seconds: float = Field(default=300, gt=0)
    trace_candidate_limit: int = Field(default=5, ge=1, le=50)
    log_max_entries: int = Field(default=200, ge=1, le=5000)
    graph_recursion_limit: int = Field(default=50, ge=10)

    llm_provider: Literal["disabled", "gateway"] = "disabled"
    llm_protocol: Literal["anthropic_messages"] = "anthropic_messages"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None
    llm_auth_style: Literal["bearer", "x_api_key"] = "bearer"
    llm_timeout_seconds: float = Field(default=60, gt=0)
    llm_max_tokens: int = Field(default=2048, ge=1, le=65536)
    llm_max_retries: int = Field(default=1, ge=0, le=3)
    llm_retry_backoff_seconds: float = Field(default=0.5, ge=0, le=10)
    llm_allow_insecure_http: bool = False

    codex_model: str | None = None
    codex_timeout_seconds: float = Field(default=300, gt=0)
    codex_bin: str | None = None

    @model_validator(mode="after")
    def validate_llm_gateway(self) -> "AppSettings":
        """只在显式启用模型网关时要求完整且安全的连接配置。"""

        if self.llm_provider == "disabled":
            return self

        missing = tuple(
            name
            for name, value in (
                ("llm_base_url", self.llm_base_url),
                ("llm_api_key", self.llm_api_key),
                ("llm_model", self.llm_model),
            )
            if value is None
            or (isinstance(value, str) and not value.strip())
            or (isinstance(value, SecretStr) and not value.get_secret_value())
        )
        if missing:
            raise ValueError(f"启用模型网关时缺少配置：{', '.join(missing)}")

        assert self.llm_base_url is not None
        parsed = urlsplit(self.llm_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("llm_base_url 必须是有效的 HTTP(S) 地址")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("llm_base_url 不得包含凭证、查询参数或片段")
        is_loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if (
            parsed.scheme == "http"
            and not is_loopback
            and not self.llm_allow_insecure_http
        ):
            raise ValueError("非本地 HTTP 模型地址必须显式启用 llm_allow_insecure_http")
        return self
