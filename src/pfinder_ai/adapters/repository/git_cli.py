"""使用本机 Git CLI 实现受限仓库物化。"""

import asyncio
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

from pfinder_ai.domain.enums import ErrorKind
from pfinder_ai.domain.errors import ProviderError
from pfinder_ai.ports.repository import RepositoryRequest, WorkspaceHandle


class GitCliRepositoryAdapter:
    """用参数数组执行只读 Git 操作，不执行仓库脚本。

    受信任域名、临时目录分配和删除策略由 GitWorkspaceManager 负责；本类
    只负责克隆、检出和解析提交。第一版不初始化 submodule，也跳过 Git LFS
    大文件下载。
    """

    _DISABLED_HOOKS_PATH = ".pfinder-hooks-disabled"

    def __init__(
        self,
        *,
        executable: str = "git",
        timeout_seconds: float = 120,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        self._executable = executable
        self._timeout_seconds = timeout_seconds

    async def materialize(
        self,
        request: RepositoryRequest,
        destination: Path,
    ) -> WorkspaceHandle:
        """浅克隆仓库并以 detached HEAD 检出请求版本。"""

        resolved_destination = destination.resolve()
        if not resolved_destination.is_dir():
            raise ProviderError(
                "Git 目标工作区不存在或不是目录",
                kind=ErrorKind.INVALID_INPUT,
                retryable=False,
            )
        if any(resolved_destination.iterdir()):
            raise ProviderError(
                "Git 目标工作区必须为空",
                kind=ErrorKind.INVALID_INPUT,
                retryable=False,
            )

        await self._run_git(
            (
                "clone",
                "--no-checkout",
                "--depth",
                "1",
                "--no-tags",
                "--no-recurse-submodules",
                request.repository_url,
                str(resolved_destination),
            ),
            repository_url=request.repository_url,
        )

        if request.requested_revision:
            await self._run_git(
                (
                    "-C",
                    str(resolved_destination),
                    "fetch",
                    "--depth",
                    "1",
                    "--no-tags",
                    "origin",
                    request.requested_revision,
                ),
                repository_url=request.repository_url,
            )
            checkout_target = "FETCH_HEAD"
        else:
            checkout_target = "HEAD"

        await self._run_git(
            (
                "-C",
                str(resolved_destination),
                "checkout",
                "--detach",
                checkout_target,
            ),
            repository_url=request.repository_url,
        )
        resolved_commit = (
            await self._run_git(
                (
                    "-C",
                    str(resolved_destination),
                    "rev-parse",
                    "HEAD",
                ),
                repository_url=request.repository_url,
            )
        ).strip()
        if len(resolved_commit) != 40:
            raise ProviderError(
                "Git 未返回完整提交编号",
                kind=ErrorKind.INVALID_RESPONSE,
                retryable=False,
            )

        return WorkspaceHandle(
            path=resolved_destination,
            repository_url=request.repository_url,
            requested_revision=request.requested_revision,
            resolved_commit=resolved_commit,
            revision_is_assumption=request.revision_is_assumption,
        )

    async def release(self, workspace: WorkspaceHandle) -> None:
        """Adapter 不持有额外资源；目录由 Manager 统一清理。"""

        del workspace

    async def _run_git(
        self,
        arguments: Sequence[str],
        *,
        repository_url: str,
    ) -> str:
        """在线程中执行无 Shell、无交互 Git 命令并返回标准输出。"""

        command = (
            self._executable,
            "-c",
            f"core.hooksPath={self._DISABLED_HOOKS_PATH}",
            "-c",
            "filter.lfs.smudge=",
            "-c",
            "filter.lfs.required=false",
            *arguments,
        )
        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        environment["GIT_LFS_SKIP_SMUDGE"] = "1"

        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=self._timeout_seconds,
            )
        except FileNotFoundError as error:
            raise ProviderError(
                "未找到 Git CLI 可执行文件",
                kind=ErrorKind.NOT_FOUND,
                retryable=False,
            ) from error
        except subprocess.TimeoutExpired as error:
            raise ProviderError(
                "Git 操作超时",
                kind=ErrorKind.TRANSIENT,
                retryable=True,
            ) from error

        if completed.returncode != 0:
            safe_error = completed.stderr.replace(
                repository_url,
                "<repository-url>",
            ).strip()[:500]
            raise ProviderError(
                f"Git 操作失败：{safe_error or '未提供错误摘要'}",
                kind=ErrorKind.TRANSIENT,
                retryable=True,
                context={"return_code": str(completed.returncode)},
            )
        return completed.stdout
