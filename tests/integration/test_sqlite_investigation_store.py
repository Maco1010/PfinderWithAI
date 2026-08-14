"""SQLiteInvestigationStore 的持久化和幂等语义测试。"""

import asyncio
from pathlib import Path

import pytest

from pfinder_ai.adapters.sqlite import SQLiteInvestigationStore
from pfinder_ai.domain.enums import ConclusionStatus, ExecutionStatus
from pfinder_ai.domain.errors import ProviderError
from pfinder_ai.domain.models import DiagnosisResult, IncidentInput, InvestigationStep


def test_sqlite_store_round_trips_incident_steps_and_result(tmp_path: Path) -> None:
    """进程内不同连接应能完整读取已保存的领域对象。"""

    async def run_case() -> None:
        store = SQLiteInvestigationStore(tmp_path / "investigations.sqlite3")
        incident = IncidentInput(
            description="合成问题",
            start_system="system-a",
            trace_id="trace-synthetic",
        )
        first_step = InvestigationStep(
            step_id="step-1",
            name="trace_finder",
            decision="找到合成 Trace",
        )
        second_step = InvestigationStep(
            step_id="step-2",
            name="result_builder",
            decision="构建未决结果",
        )
        result = DiagnosisResult(
            execution_status=ExecutionStatus.COMPLETED,
            conclusion_status=ConclusionStatus.UNRESOLVED,
            summary="现有证据不足",
            confidence=0,
            investigation_steps=(first_step, second_step),
            termination_reason="合成测试结束",
        )

        await store.initialize()
        await store.save_incident("investigation-1", incident)
        await store.append_step("investigation-1", first_step)
        await store.append_step("investigation-1", first_step)
        await store.append_step("investigation-1", second_step)
        await store.save_result("investigation-1", result)

        assert await store.load_incident("investigation-1") == incident
        assert await store.list_steps("investigation-1") == (
            first_step,
            second_step,
        )
        assert await store.load_result("investigation-1") == result

    asyncio.run(run_case())


def test_sqlite_store_rejects_conflicting_step_identity(tmp_path: Path) -> None:
    """相同步骤编号出现不同内容时不能静默覆盖审计历史。"""

    async def run_case() -> None:
        store = SQLiteInvestigationStore(tmp_path / "investigations.sqlite3")
        await store.append_step(
            "investigation-1",
            InvestigationStep(
                step_id="step-1",
                name="trace_finder",
                decision="第一次判断",
            ),
        )

        with pytest.raises(ProviderError):
            await store.append_step(
                "investigation-1",
                InvestigationStep(
                    step_id="step-1",
                    name="trace_finder",
                    decision="冲突判断",
                ),
            )

    asyncio.run(run_case())
