"""GitWorkspaceManager 的路径边界和清理测试。"""

import asyncio
from pathlib import Path

import pytest

from pfinder_ai.domain.enums import ErrorKind
from pfinder_ai.domain.errors import ProviderError
from pfinder_ai.domain.models import SystemContext
from pfinder_ai.ports.repository import RepositoryRequest, WorkspaceHandle
from pfinder_ai.services.workspace_manager import GitWorkspaceManager


class StubRepositoryAdapter:
    """只在测试临时目录中创建合成仓库内容。"""

    released = False

    async def materialize(
        self,
        request: RepositoryRequest,
        destination: Path,
    ) -> WorkspaceHandle:
        (destination / "README.md").write_text("synthetic repository", encoding="utf-8")
        return WorkspaceHandle(
            path=destination,
            repository_url=request.repository_url,
            requested_revision=request.requested_revision,
            resolved_commit="a" * 40,
            revision_is_assumption=request.revision_is_assumption,
        )

    async def release(self, workspace: WorkspaceHandle) -> None:
        self.released = True


def test_workspace_is_removed_after_context_exit(tmp_path: Path) -> None:
    """代码分析结束后必须释放 Adapter 并清理临时目录。"""

    async def run_case() -> None:
        adapter = StubRepositoryAdapter()
        manager = GitWorkspaceManager(
            adapter,
            trusted_hosts=frozenset({"git.example.local"}),
            base_directory=tmp_path,
        )
        context = SystemContext(
            system="system-d",
            repository_url="https://git.example.local/team/system-d.git",
            revision="release-1",
        )

        async with manager.prepare(context) as workspace:
            workspace_path = workspace.path
            assert (workspace_path / "README.md").exists()

        assert adapter.released is True
        assert not workspace_path.exists()

    asyncio.run(run_case())


def test_untrusted_git_host_is_rejected(tmp_path: Path) -> None:
    """未进入白名单的仓库地址不能触发任何物化操作。"""

    async def run_case() -> None:
        manager = GitWorkspaceManager(
            StubRepositoryAdapter(),
            trusted_hosts=frozenset({"git.example.local"}),
            base_directory=tmp_path,
        )
        context = SystemContext(
            system="system-d",
            repository_url="https://untrusted.example/system-d.git",
        )

        with pytest.raises(ProviderError) as error:
            async with manager.prepare(context):
                pass

        assert error.value.kind is ErrorKind.UNAUTHORIZED

    asyncio.run(run_case())
