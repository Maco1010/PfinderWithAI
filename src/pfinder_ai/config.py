"""从环境变量加载非敏感应用配置。"""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """本地 Demo 配置；真实密钥不属于该模型。"""

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

    codex_model: str | None = None
    codex_timeout_seconds: float = Field(default=300, gt=0)
    codex_bin: str | None = None
