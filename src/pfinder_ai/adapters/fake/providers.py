"""用于本地纵向切片的合成 Provider 实现。"""

from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel

from pfinder_ai.domain.enums import ErrorKind, EvidenceSource
from pfinder_ai.domain.errors import ProviderError
from pfinder_ai.domain.models import (
    DiagnosisResult,
    Evidence,
    Hypothesis,
    IncidentInput,
    InvestigationStep,
    SystemContext,
    TraceCandidate,
)
from pfinder_ai.ports.code_analysis import (
    CodeInvestigationRequest,
    CodeInvestigationResult,
)
from pfinder_ai.ports.logs import LogQuery
from pfinder_ai.ports.metadata import SystemResolution
from pfinder_ai.ports.repository import RepositoryRequest, WorkspaceHandle
from pfinder_ai.ports.trace import TraceQuery


class FakeLLMProvider:
    """按任务返回预设模型，便于测试结构化输出边界。"""

    def __init__(self, outputs: Mapping[str, BaseModel]) -> None:
        self._outputs = dict(outputs)

    @property
    def provider_name(self) -> str:
        """返回稳定的合成供应商名称。"""

        return "fake"

    async def generate_structured[StructuredModel: BaseModel](
        self,
        *,
        task: str,
        prompt: str,
        output_type: type[StructuredModel],
    ) -> StructuredModel:
        """重新校验预设输出，模拟真实 Adapter 的结构化解析步骤。"""

        del prompt
        output = self._outputs.get(task)
        if output is None:
            raise ProviderError(
                f"FakeLLMProvider 未配置任务 {task}",
                kind=ErrorKind.NOT_FOUND,
                retryable=False,
            )
        return output_type.model_validate(output.model_dump())


class FakeMetadataProvider:
    """从内存映射解析系统上下文。"""

    def __init__(self, contexts: Mapping[str, SystemContext]) -> None:
        self._contexts = {
            system.casefold(): context for system, context in contexts.items()
        }

    async def resolve_system(self, system: str) -> SystemResolution:
        """返回零个或一个合成系统上下文。"""

        context = self._contexts.get(system.casefold())
        return SystemResolution(candidates=(context,) if context else ())


class FakeTraceProvider:
    """返回预设的 Provider 中立 Trace 候选。"""

    def __init__(self, candidates: tuple[TraceCandidate, ...]) -> None:
        self._candidates = candidates
        self.last_query: TraceQuery | None = None

    async def find_candidates(self, query: TraceQuery) -> tuple[TraceCandidate, ...]:
        """记录查询范围并按调用方上限裁剪合成候选。"""

        self.last_query = query
        return self._candidates[: query.limit]


class FakeLogProvider:
    """按系统返回预设的已脱敏日志证据。"""

    def __init__(
        self,
        evidence_by_system: Mapping[str, tuple[Evidence, ...]],
    ) -> None:
        self._evidence_by_system = {
            system.casefold(): evidence
            for system, evidence in evidence_by_system.items()
        }
        self.last_query: LogQuery | None = None

    async def query(self, query: LogQuery) -> tuple[Evidence, ...]:
        """返回不超过显式条数上限的合成证据。"""

        self.last_query = query
        evidence = self._evidence_by_system.get(query.target.system.casefold(), ())
        return evidence[: query.max_entries]


class FakeRepositoryAdapter:
    """在 Manager 分配的目录内生成最小合成代码仓库。"""

    def __init__(self, files: Mapping[str, str] | None = None) -> None:
        self._files = dict(
            files
            or {
                "service.py": (
                    "def create_order():\n"
                    "    raise TimeoutError('synthetic downstream timeout')\n"
                )
            }
        )
        self.released_workspaces: list[Path] = []

    async def materialize(
        self,
        request: RepositoryRequest,
        destination: Path,
    ) -> WorkspaceHandle:
        """只写入合成文本文件，不执行仓库脚本或网络操作。"""

        for relative_path, content in self._files.items():
            file_path = (destination / relative_path).resolve()
            if not file_path.is_relative_to(destination.resolve()):
                raise ProviderError(
                    "Fake 仓库文件路径越过临时工作区",
                    kind=ErrorKind.INVALID_INPUT,
                    retryable=False,
                )
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        return WorkspaceHandle(
            path=destination,
            repository_url=request.repository_url,
            requested_revision=request.requested_revision,
            resolved_commit="f" * 40,
            revision_is_assumption=request.revision_is_assumption,
        )

    async def release(self, workspace: WorkspaceHandle) -> None:
        """记录释放调用，目录删除仍由 GitWorkspaceManager 负责。"""

        self.released_workspaces.append(workspace.path)


class FakeCodeAnalysisProvider:
    """根据当前日志证据生成可验证的合成代码结论。"""

    async def investigate(
        self,
        request: CodeInvestigationRequest,
    ) -> CodeInvestigationResult:
        """验证工作区存在，并返回代码证据与根因候选。"""

        source_path = request.workspace.path / "service.py"
        if not source_path.exists():
            raise ProviderError(
                "合成代码工作区缺少 service.py",
                kind=ErrorKind.NOT_FOUND,
                retryable=False,
            )

        evidence = Evidence(
            evidence_id=f"code:{request.target.system}:timeout-handling",
            source=EvidenceSource.CODE,
            summary="超时异常未被转换为可重试或可降级结果",
            locator=(
                f"commit={request.workspace.resolved_commit};"
                "path=service.py;line=2"
            ),
            system=request.target.system,
        )
        log_evidence = next(
            (
                item
                for item in request.trace_and_log_evidence
                if item.source is EvidenceSource.LOG
            ),
            None,
        )
        supporting_ids: tuple[str, ...] = (evidence.evidence_id,)
        if log_evidence is not None:
            supporting_ids = (log_evidence.evidence_id, evidence.evidence_id)

        hypothesis = Hypothesis(
            hypothesis_id=f"hypothesis:{request.target.system}:timeout",
            statement=(
                f"{request.target.system} 未正确处理下游超时，导致请求失败"
            ),
            target_system=request.target.system,
            confidence=0.9 if log_evidence is not None else 0.55,
            supporting_evidence_ids=supporting_ids,
            open_questions=(
                ()
                if log_evidence is not None
                else ("需要目标系统的超时日志进行交叉验证",)
            ),
        )
        return CodeInvestigationResult(
            evidence=(evidence,),
            hypotheses=(hypothesis,),
            unresolved_questions=hypothesis.open_questions,
        )


class InMemoryInvestigationStore:
    """测试使用的审计存储，不提供进程间恢复能力。"""

    def __init__(self) -> None:
        self._incidents: dict[str, IncidentInput] = {}
        self._steps: dict[str, list[InvestigationStep]] = {}
        self._results: dict[str, DiagnosisResult] = {}

    async def save_incident(
        self,
        investigation_id: str,
        incident: IncidentInput,
    ) -> None:
        """保存合成调查输入，相同编号重复写入必须一致。"""

        existing = self._incidents.get(investigation_id)
        if existing is not None and existing != incident:
            raise ProviderError(
                "同一调查编号对应了不同输入",
                kind=ErrorKind.INVALID_INPUT,
                retryable=False,
            )
        self._incidents[investigation_id] = incident

    async def load_incident(self, investigation_id: str) -> IncidentInput | None:
        """返回内存中的调查输入。"""

        return self._incidents.get(investigation_id)

    async def append_step(
        self,
        investigation_id: str,
        step: InvestigationStep,
    ) -> None:
        """按步骤编号幂等追加调查轨迹。"""

        steps = self._steps.setdefault(investigation_id, [])
        if all(existing.step_id != step.step_id for existing in steps):
            steps.append(step)

    async def list_steps(self, investigation_id: str) -> tuple[InvestigationStep, ...]:
        """按写入顺序返回步骤快照。"""

        return tuple(self._steps.get(investigation_id, ()))

    async def save_result(
        self,
        investigation_id: str,
        result: DiagnosisResult,
    ) -> None:
        """覆盖保存同一调查的最新最终结果。"""

        self._results[investigation_id] = result

    async def load_result(self, investigation_id: str) -> DiagnosisResult | None:
        """返回内存中的最终结果快照。"""

        return self._results.get(investigation_id)
