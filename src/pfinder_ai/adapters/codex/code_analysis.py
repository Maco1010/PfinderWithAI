"""通过 Codex Python SDK 实现受限代码库调查。"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from openai_codex import (
    ApprovalMode,
    AsyncCodex,
    CodexConfig,
    CodexError,
    Sandbox,
    is_retryable_error,
)
from openai_codex.models import JsonObject
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from pfinder_ai.domain.enums import ErrorKind, EvidenceSource, NextAction
from pfinder_ai.domain.errors import ProviderError, StructuredOutputError
from pfinder_ai.domain.models import Evidence, Hypothesis, NextHop
from pfinder_ai.monitoring import UsageMonitor
from pfinder_ai.ports.code_analysis import (
    CodeAnalysisProvider,
    CodeInvestigationRequest,
    CodeInvestigationResult,
    SupplementalEvidenceRequest,
)


@dataclass(frozen=True, slots=True)
class CodexAdapterSettings:
    """Codex 本地运行时的非敏感配置。"""

    model: str | None = None
    timeout_seconds: float = 300
    codex_bin: str | None = None

    def __post_init__(self) -> None:
        """拒绝无效超时，模型和认证仍由外部配置提供。"""

        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")


class CodexRunner(Protocol):
    """隔离 Codex SDK 生命周期，便于测试结构化转换。"""

    async def run(
        self,
        *,
        cwd: Path,
        prompt: str,
        output_schema: Mapping[str, Any],
    ) -> str:
        """在只读工作区执行一次结构化代码调查。"""

        ...


class CodexSDKRunner:
    """使用当前 Codex Python SDK 启动一次临时只读线程。"""

    _DEVELOPER_INSTRUCTIONS = (
        "你是受限的代码调查子 Agent。只能读取当前工作区并进行静态分析；"
        "不得修改文件、执行项目代码、访问生产系统或请求权限升级。"
        "所有结论必须引用 commit、文件路径和行号，并严格返回声明的 JSON Schema。"
    )

    def __init__(
        self,
        settings: CodexAdapterSettings | None = None,
        *,
        usage_monitor: UsageMonitor | None = None,
    ) -> None:
        self._settings = settings or CodexAdapterSettings()
        self._usage_monitor = usage_monitor

    async def run(
        self,
        *,
        cwd: Path,
        prompt: str,
        output_schema: Mapping[str, Any],
    ) -> str:
        """禁用审批升级并以 read-only Sandbox 运行 Codex。"""

        if self._usage_monitor is None:
            return await self._run_once(cwd, prompt, output_schema)

        async with self._usage_monitor.track(
            provider="codex",
            operation="code_investigation",
            details={"model": self._settings.model or "configured-default"},
        ) as measurement:
            response, input_tokens, output_tokens = await self._run_with_usage(
                cwd,
                prompt,
                output_schema,
            )
            measurement.set_model_usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            return response

    async def _run_once(
        self,
        cwd: Path,
        prompt: str,
        output_schema: Mapping[str, Any],
    ) -> str:
        """执行一次调查，并丢弃调用方未请求的用量返回。"""

        response, _, _ = await self._run_with_usage(cwd, prompt, output_schema)
        return response

    async def _run_with_usage(
        self,
        cwd: Path,
        prompt: str,
        output_schema: Mapping[str, Any],
    ) -> tuple[str, int | None, int | None]:
        """执行 SDK 调用并提取明确返回的本轮 Token。"""

        try:
            async with asyncio.timeout(self._settings.timeout_seconds):
                config = CodexConfig(
                    codex_bin=self._settings.codex_bin,
                    cwd=str(cwd),
                )
                async with AsyncCodex(config=config) as codex:
                    thread = await codex.thread_start(
                        approval_mode=ApprovalMode.deny_all,
                        cwd=str(cwd),
                        developer_instructions=self._DEVELOPER_INSTRUCTIONS,
                        ephemeral=True,
                        model=self._settings.model,
                        sandbox=Sandbox.read_only,
                    )
                    turn = await thread.run(
                        prompt,
                        approval_mode=ApprovalMode.deny_all,
                        cwd=str(cwd),
                        output_schema=cast(JsonObject, dict(output_schema)),
                        sandbox=Sandbox.read_only,
                    )
        except TimeoutError as error:
            raise ProviderError(
                "Codex 代码调查超时",
                kind=ErrorKind.TRANSIENT,
                retryable=True,
            ) from error
        except (CodexError, RuntimeError, OSError) as error:
            retryable = is_retryable_error(error)
            raise ProviderError(
                "Codex 代码调查调用失败",
                kind=ErrorKind.TRANSIENT if retryable else ErrorKind.INTERNAL,
                retryable=retryable,
                context={"error_type": type(error).__name__},
            ) from error

        if not turn.final_response:
            raise ProviderError(
                "Codex 未返回最终结构化响应",
                kind=ErrorKind.INVALID_RESPONSE,
                retryable=True,
            )
        usage = turn.usage.last if turn.usage is not None else None
        return (
            turn.final_response,
            usage.input_tokens if usage is not None else None,
            usage.output_tokens if usage is not None else None,
        )


class _CodexSupplementalRequest(BaseModel):
    """Codex JSON 输出中的补充证据请求。"""

    model_config = ConfigDict(extra="forbid")

    action: NextAction
    reason: str = Field(min_length=1)
    search_hints: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_action(self) -> "_CodexSupplementalRequest":
        """子 Agent 只能请求更多证据，不能自行决定跨系统路由。"""

        allowed = {NextAction.GATHER_LOGS, NextAction.INVESTIGATE_CODE}
        if self.action not in allowed:
            raise ValueError("Codex 只能请求更多日志或代码证据")
        return self


class _CodexInvestigationOutput(BaseModel):
    """Codex 最终响应必须满足的结构化 Schema。"""

    model_config = ConfigDict(extra="forbid")

    evidence: tuple[Evidence, ...] = ()
    hypotheses: tuple[Hypothesis, ...] = ()
    supplemental_requests: tuple[_CodexSupplementalRequest, ...] = ()
    discovered_dependencies: tuple[NextHop, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    partial: bool = False


class CodexCodeAnalysisProvider(CodeAnalysisProvider):
    """把领域请求映射为 Codex Prompt，并校验返回的领域对象。"""

    def __init__(self, runner: CodexRunner) -> None:
        self._runner = runner

    async def investigate(
        self,
        request: CodeInvestigationRequest,
    ) -> CodeInvestigationResult:
        """执行一次受限代码调查并转换为 Provider 中立结果。"""

        response = await self._runner.run(
            cwd=request.workspace.path,
            prompt=self._build_prompt(request),
            output_schema=_CodexInvestigationOutput.model_json_schema(),
        )
        try:
            parsed = _CodexInvestigationOutput.model_validate_json(response)
        except ValidationError as error:
            raise StructuredOutputError(
                "Codex 返回结果无法通过结构化校验",
                context={"validation_errors": str(error.error_count())},
            ) from error

        if any(item.source is not EvidenceSource.CODE for item in parsed.evidence):
            raise StructuredOutputError("Codex 返回了非代码类型证据")
        if any(not item.redacted for item in parsed.evidence):
            raise StructuredOutputError("Codex 返回了未脱敏代码证据")

        return CodeInvestigationResult(
            evidence=parsed.evidence,
            hypotheses=parsed.hypotheses,
            supplemental_requests=tuple(
                SupplementalEvidenceRequest(
                    action=item.action,
                    reason=item.reason,
                    search_hints=item.search_hints,
                )
                for item in parsed.supplemental_requests
            ),
            discovered_dependencies=parsed.discovered_dependencies,
            unresolved_questions=parsed.unresolved_questions,
            partial=parsed.partial,
        )

    def _build_prompt(self, request: CodeInvestigationRequest) -> str:
        """构造仅包含静态分析所需摘要和证据引用的 Prompt。"""

        evidence_lines = "\n".join(
            f"- [{item.evidence_id}] {item.source.value} | {item.summary} | {item.locator}"
            for item in request.trace_and_log_evidence
        ) or "- 当前没有 Trace 或日志证据"
        hints = "、".join(request.search_hints) or "无"
        business_key_names = "、".join(request.incident.business_keys) or "无"
        return (
            "请在当前只读代码库中调查以下故障，并返回严格符合 JSON Schema 的结果。\n"
            f"目标系统：{request.target.system}\n"
            f"目标入口：{request.target.operation or '未知'}\n"
            f"TraceID：{request.target.trace_id or request.incident.trace_id or '未知'}\n"
            f"SpanID：{request.target.span_id or '未知'}\n"
            f"故障描述：{request.incident.description}\n"
            f"业务标识字段名：{business_key_names}\n"
            f"补充搜索提示：{hints}\n"
            f"仓库提交：{request.workspace.resolved_commit}\n"
            "已有证据：\n"
            f"{evidence_lines}\n"
            "要求：只进行静态分析，不修改文件，不执行项目代码。代码证据 locator 必须包含"
            " commit、path 和 line；区分事实、推断和未知项。若证据不足，返回结构化补充"
            "证据请求；只有发现 Trace 队列之外的新依赖时才返回 discovered_dependencies。"
        )
