"""临时代码工作区所需的仓库操作接口。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RepositoryRequest:
    """准备指定仓库版本所需的输入。"""

    repository_url: str
    requested_revision: str | None
    revision_is_assumption: bool = False


@dataclass(frozen=True, slots=True)
class WorkspaceHandle:
    """已经准备完成、可交给 CodeInvestigator 的工作区引用。"""

    path: Path
    repository_url: str
    requested_revision: str | None
    resolved_commit: str
    revision_is_assumption: bool


class RepositoryWorkspacePort(Protocol):
    """隔离 Git CLI、Git SDK 或未来代码快照服务的差异。"""

    async def materialize(
        self,
        request: RepositoryRequest,
        destination: Path,
    ) -> WorkspaceHandle:
        """把指定版本物化到已分配的临时目录。"""

        ...

    async def release(self, workspace: WorkspaceHandle) -> None:
        """释放 Adapter 持有的资源；目录生命周期由上层统一管理。"""

        ...

