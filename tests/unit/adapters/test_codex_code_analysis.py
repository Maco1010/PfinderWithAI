"""CodexCodeAnalysisProvider 的 Prompt 和结构化结果测试。"""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from pfinder_ai.adapters.codex import CodexCodeAnalysisProvider
from pfinder_ai.domain.enums import EvidenceSource, TargetSource
from pfinder_ai.domain.errors import StructuredOutputError
from pfinder_ai.domain.models import (
    Evidence,
    IncidentInput,
    InvestigationTarget,
)
from pfinder_ai.ports.code_analysis import CodeInvestigationRequest
from pfinder_ai.ports.repository import WorkspaceHandle


class StubCodexRunner:
    """返回预设 JSON，并记录实际传入的安全边界。"""

    def __init__(self, response: str) -> None:
        self.response = response
        self.cwd: Path | None = None
        self.prompt: str | None = None
        self.output_schema: dict[str, Any] | None = None

    async def run(
        self,
        *,
        cwd: Path,
        prompt: str,
        output_schema: dict[str, Any],
    ) -> str:
        """记录调用并返回合成响应。"""

        self.cwd = cwd
        self.prompt = prompt
        self.output_schema = output_schema
        return self.response


def _request(tmp_path: Path) -> CodeInvestigationRequest:
    """创建不包含真实代码和日志的合成调查请求。"""

    target = InvestigationTarget(
        target_id="trace-1:span-1",
        system="system-b",
        source=TargetSource.TRACE_CANDIDATE,
        reason="合成异常",
        priority=0,
        trace_id="trace-1",
        span_id="span-1",
        operation="create_order",
    )
    return CodeInvestigationRequest(
        incident=IncidentInput(
            description="合成下单失败",
            business_keys={"order_id": "sensitive-value-not-forwarded"},
            start_system="system-a",
            trace_id="trace-1",
        ),
        target=target,
        workspace=WorkspaceHandle(
            path=tmp_path,
            repository_url="https://git.example.local/system-b.git",
            requested_revision="release-synthetic",
            resolved_commit="c" * 40,
            revision_is_assumption=False,
        ),
        trace_and_log_evidence=(
            Evidence(
                evidence_id="log:synthetic:1",
                source=EvidenceSource.LOG,
                summary="合成超时日志",
                locator="synthetic-log:1",
                system="system-b",
            ),
        ),
    )


def test_codex_provider_parses_structured_result(tmp_path: Path) -> None:
    """有效 JSON 应转换为领域结果，且 Prompt 不包含业务标识值。"""

    response = json.dumps(
        {
            "evidence": [
                {
                    "evidence_id": "code:synthetic:1",
                    "source": "code",
                    "summary": "超时未处理",
                    "locator": f"commit={'c' * 40};path=service.py;line=10",
                    "system": "system-b",
                    "redacted": True,
                }
            ],
            "hypotheses": [
                {
                    "hypothesis_id": "hypothesis:synthetic:1",
                    "statement": "超时未处理导致失败",
                    "target_system": "system-b",
                    "confidence": 0.9,
                    "supporting_evidence_ids": [
                        "log:synthetic:1",
                        "code:synthetic:1",
                    ],
                }
            ],
        }
    )
    runner = StubCodexRunner(response)
    result = asyncio.run(CodexCodeAnalysisProvider(runner).investigate(_request(tmp_path)))

    assert result.evidence[0].source is EvidenceSource.CODE
    assert result.hypotheses[0].confidence == 0.9
    assert runner.cwd == tmp_path
    assert runner.output_schema is not None
    assert runner.prompt is not None
    assert "order_id" in runner.prompt
    assert "sensitive-value-not-forwarded" not in runner.prompt


def test_codex_provider_rejects_invalid_json(tmp_path: Path) -> None:
    """无法通过 Schema 校验的模型输出必须显式失败。"""

    runner = StubCodexRunner("not-json")
    with pytest.raises(StructuredOutputError):
        asyncio.run(
            CodexCodeAnalysisProvider(runner).investigate(_request(tmp_path))
        )
