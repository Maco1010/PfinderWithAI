"""应用服务和 CLI Fake 纵向切片测试。"""

import asyncio
import json
from pathlib import Path

from typer.testing import CliRunner

from pfinder_ai.bootstrap import build_application
from pfinder_ai.cli import app
from pfinder_ai.config import AppSettings
from pfinder_ai.domain.enums import ConclusionStatus
from pfinder_ai.domain.models import IncidentInput


def test_application_service_persists_input_and_steps(tmp_path: Path) -> None:
    """应用服务应保存输入、最终结果和独立可查询的步骤轨迹。"""

    async def run_case() -> None:
        bundle = build_application(
            AppSettings(
                database_path=tmp_path / "investigations.sqlite3",
                workspace_base_directory=tmp_path / "workspaces",
            )
        )
        incident = IncidentInput(
            description="合成下单失败",
            start_system="system-a",
            trace_id="trace-synthetic",
        )
        result = await bundle.service.investigate(
            incident,
            investigation_id="investigation-application",
        )

        assert result.conclusion_status is ConclusionStatus.VERIFIED
        assert await bundle.store.load_incident("investigation-application") == incident
        assert await bundle.store.load_result("investigation-application") == result
        assert await bundle.store.list_steps("investigation-application")

    asyncio.run(run_case())


def test_cli_emits_machine_readable_json(tmp_path: Path) -> None:
    """JSON 模式不得混入进度文本，并应返回静态验证结果。"""

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "investigate",
            "合成下单失败",
            "--start-system",
            "system-a",
            "--business-key",
            "order_id=synthetic-001",
            "--time-description",
            "最近五分钟",
            "--investigation-id",
            "investigation-cli",
            "--json",
        ],
        env={
            "PFINDER_AI_DATABASE_PATH": str(tmp_path / "cli.sqlite3"),
            "PFINDER_AI_WORKSPACE_BASE_DIRECTORY": str(tmp_path / "workspaces"),
        },
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["conclusion_status"] == "verified"
    assert payload["verification"]["runtime_verified"] is False
