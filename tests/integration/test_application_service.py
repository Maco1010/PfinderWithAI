"""应用服务和 CLI Fake 纵向切片测试。"""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from pfinder_ai.adapters.llm import GatewayLLMProvider
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
                llm_provider="disabled",
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
            "PFINDER_AI_LLM_PROVIDER": "disabled",
        },
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["conclusion_status"] == "verified"
    assert payload["verification"]["runtime_verified"] is False


def test_application_injects_gateway_llm_into_clue_extractor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式启用网关时，主图应通过真实 Adapter 边界提取线索。"""

    calls = 0

    async def fake_post(
        self: GatewayLLMProvider,
        request: dict[str, Any],
    ) -> httpx.Response:
        del self
        nonlocal calls
        calls += 1
        assert request["tool_choice"]["name"] == "submit_structured_result"
        return httpx.Response(
            200,
            json={
                "type": "message",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "submit_structured_result",
                        "input": {
                            "description": "模型不得覆盖显式问题描述",
                            "business_keys": {"model_key": "synthetic-value"},
                            "start_system": "system-b",
                            "trace_id": "trace-from-model",
                        },
                    }
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 20, "output_tokens": 8},
            },
        )

    monkeypatch.setattr(GatewayLLMProvider, "_post", fake_post)

    async def run_case() -> None:
        bundle = build_application(
            AppSettings(  # type: ignore[call-arg]
                database_path=tmp_path / "gateway.sqlite3",
                workspace_base_directory=tmp_path / "gateway-workspaces",
                llm_provider="gateway",
                llm_base_url="https://llm.example.test",
                llm_api_key=SecretStr("synthetic-secret"),
                llm_model="synthetic-model",
                llm_retry_backoff_seconds=0,
                _env_file=None,
            )
        )
        result = await bundle.service.investigate(
            IncidentInput(
                description="合成下单失败",
                start_system="system-a",
                trace_id="trace-synthetic",
            ),
            investigation_id="investigation-gateway",
        )

        assert result.conclusion_status is ConclusionStatus.VERIFIED
        records = bundle.usage_monitor.snapshot()
        assert len(records) == 1
        assert records[0].provider == "llm_gateway"
        assert records[0].operation == "clue_extraction"
        assert records[0].input_tokens == 20

    asyncio.run(run_case())
    assert calls == 1
