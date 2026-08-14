"""Git CLI Adapter 的本地仓库集成测试。"""

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from pfinder_ai.adapters.repository import GitCliRepositoryAdapter
from pfinder_ai.ports.repository import RepositoryRequest


def test_git_adapter_materializes_requested_commit(tmp_path: Path) -> None:
    """Adapter 应检出请求提交并返回完整 commit，同时不依赖网络。"""

    git = shutil.which("git")
    if git is None:
        pytest.skip("当前环境没有 Git CLI")

    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    _run(git, "init", str(source))
    _run(git, "-C", str(source), "config", "user.name", "Synthetic User")
    _run(
        git,
        "-C",
        str(source),
        "config",
        "user.email",
        "synthetic@example.invalid",
    )
    (source / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
    _run(git, "-C", str(source), "add", "service.py")
    _run(git, "-C", str(source), "commit", "-m", "synthetic commit")
    commit = _run(git, "-C", str(source), "rev-parse", "HEAD").strip()

    workspace = asyncio.run(
        GitCliRepositoryAdapter(executable=git).materialize(
            RepositoryRequest(
                repository_url=source.as_uri(),
                requested_revision=commit,
            ),
            destination,
        )
    )

    assert workspace.resolved_commit == commit
    assert workspace.path == destination.resolve()
    assert (workspace.path / "service.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def _run(executable: str, *arguments: str) -> str:
    """执行仅针对测试临时仓库的 Git 命令。"""

    completed = subprocess.run(
        (executable, *arguments),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout
