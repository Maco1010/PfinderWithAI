"""临时代码工作区的安全策略和生命周期管理。"""

import re
import shutil
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from pfinder_ai.domain.enums import ErrorKind
from pfinder_ai.domain.errors import ProviderError
from pfinder_ai.domain.models import SystemContext
from pfinder_ai.ports.repository import (
    RepositoryRequest,
    RepositoryWorkspacePort,
    WorkspaceHandle,
)


class GitWorkspaceManager:
    """在受控临时目录中准备并释放代码仓库。

    Manager 负责策略，RepositoryWorkspacePort 负责具体仓库操作。所有删除
    都仅针对本实例亲自创建并登记的临时目录，避免误删用户工作区。
    """

    _SCP_HOST_PATTERN = re.compile(r"^[^@]+@(?P<host>[^:]+):")

    def __init__(
        self,
        repository: RepositoryWorkspacePort,
        *,
        trusted_hosts: frozenset[str],
        base_directory: Path | None = None,
    ) -> None:
        self._repository = repository
        self._trusted_hosts = frozenset(host.casefold() for host in trusted_hosts)
        self._base_directory = base_directory
        self._managed_paths: set[Path] = set()

    @asynccontextmanager
    async def prepare(self, context: SystemContext) -> AsyncIterator[WorkspaceHandle]:
        """准备代码工作区，并在离开上下文时保证清理。"""

        if not context.repository_url:
            raise ProviderError(
                "目标系统缺少 Git 仓库地址",
                kind=ErrorKind.INVALID_INPUT,
                retryable=False,
                context={"system": context.system},
            )

        host = self._extract_host(context.repository_url)
        if host.casefold() not in self._trusted_hosts:
            raise ProviderError(
                "Git 仓库地址不在受信任域名白名单中",
                kind=ErrorKind.UNAUTHORIZED,
                retryable=False,
                context={"system": context.system, "host": host},
            )

        if self._base_directory is not None:
            self._base_directory.mkdir(parents=True, exist_ok=True)

        destination = Path(
            tempfile.mkdtemp(prefix="pfinder-ai-", dir=self._base_directory)
        ).resolve()
        self._managed_paths.add(destination)
        workspace: WorkspaceHandle | None = None

        try:
            workspace = await self._repository.materialize(
                RepositoryRequest(
                    repository_url=context.repository_url,
                    requested_revision=context.revision,
                    revision_is_assumption=context.revision_is_assumption,
                ),
                destination,
            )
            self._validate_workspace_path(workspace, destination)
            yield workspace
        finally:
            try:
                if workspace is not None:
                    await self._repository.release(workspace)
            finally:
                # 即使 Adapter 的释放动作失败，也不能遗留本地临时仓库。
                self._cleanup_managed_directory(destination)

    def _extract_host(self, repository_url: str) -> str:
        """同时解析 HTTPS/SSH URL 和常见的 SCP 风格 Git 地址。"""

        parsed = urlparse(repository_url)
        if parsed.hostname:
            return parsed.hostname

        scp_match = self._SCP_HOST_PATTERN.match(repository_url)
        if scp_match:
            return scp_match.group("host")

        raise ProviderError(
            "无法从 Git 仓库地址解析主机名",
            kind=ErrorKind.INVALID_INPUT,
            retryable=False,
        )

    def _validate_workspace_path(
        self,
        workspace: WorkspaceHandle,
        destination: Path,
    ) -> None:
        """禁止 Adapter 返回临时目录之外的路径。"""

        resolved_workspace = workspace.path.resolve()
        if (
            resolved_workspace != destination
            and not resolved_workspace.is_relative_to(destination)
        ):
            raise ProviderError(
                "仓库 Adapter 返回了临时目录之外的工作区",
                kind=ErrorKind.INTERNAL,
                retryable=False,
            )

    def _cleanup_managed_directory(self, destination: Path) -> None:
        """只删除由当前 Manager 创建并登记的精确目录。"""

        resolved_destination = destination.resolve()
        if resolved_destination not in self._managed_paths:
            raise RuntimeError("拒绝清理未登记的临时工作区")

        self._managed_paths.remove(resolved_destination)
        shutil.rmtree(resolved_destination, ignore_errors=True)
