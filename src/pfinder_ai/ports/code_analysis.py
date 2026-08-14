"""CodeInvestigator 子 Agent 的调用接口。"""

from dataclasses import dataclass
from typing import Protocol

from pfinder_ai.domain.enums import NextAction
from pfinder_ai.domain.models import (
    Evidence,
    Hypothesis,
    IncidentInput,
    InvestigationTarget,
    NextHop,
)
from pfinder_ai.ports.repository import WorkspaceHandle


@dataclass(frozen=True, slots=True)
class SupplementalEvidenceRequest:
    """代码调查无法自行满足的补充证据请求。"""

    action: NextAction
    reason: str
    search_hints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CodeInvestigationRequest:
    """主 Agent 委派给代码调查子 Agent 的最小上下文。"""

    incident: IncidentInput
    target: InvestigationTarget
    workspace: WorkspaceHandle
    trace_and_log_evidence: tuple[Evidence, ...]
    search_hints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CodeInvestigationResult:
    """CodeAnalysisProvider 返回的结构化调查结果。"""

    evidence: tuple[Evidence, ...] = ()
    hypotheses: tuple[Hypothesis, ...] = ()
    supplemental_requests: tuple[SupplementalEvidenceRequest, ...] = ()
    discovered_dependencies: tuple[NextHop, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    partial: bool = False


class CodeAnalysisProvider(Protocol):
    """屏蔽 Codex SDK 或其他代码分析实现。"""

    async def investigate(self, request: CodeInvestigationRequest) -> CodeInvestigationResult:
        """在受限工作区内执行只读代码调查。"""

        ...
