"""主调查图的依赖注入边界。"""

from dataclasses import dataclass, field

from pfinder_ai.graph.policy import GraphExecutionPolicy
from pfinder_ai.ports.code_analysis import CodeAnalysisProvider
from pfinder_ai.ports.llm import LLMProvider
from pfinder_ai.ports.logs import LogProvider
from pfinder_ai.ports.metadata import MetadataProvider
from pfinder_ai.ports.stores import InvestigationStore
from pfinder_ai.ports.trace import TraceProvider
from pfinder_ai.services.trace_analysis import TraceAnalysisService
from pfinder_ai.services.verification import HypothesisVerifier
from pfinder_ai.services.workspace_manager import GitWorkspaceManager


@dataclass(frozen=True, slots=True)
class GraphDependencies:
    """组合根提供给图构建器的 Ports、Services 与执行策略。"""

    metadata: MetadataProvider
    traces: TraceProvider
    logs: LogProvider
    code_analysis: CodeAnalysisProvider
    workspaces: GitWorkspaceManager
    store: InvestigationStore
    policy: GraphExecutionPolicy
    llm: LLMProvider | None = None
    trace_analyser: TraceAnalysisService = field(
        default_factory=TraceAnalysisService
    )
    hypothesis_verifier: HypothesisVerifier = field(
        default_factory=HypothesisVerifier
    )
    trace_candidate_limit: int = 5
    log_max_entries: int = 200

    def __post_init__(self) -> None:
        """拒绝无效检索范围，避免 Adapter 获得无界查询请求。"""

        if self.trace_candidate_limit < 1:
            raise ValueError("trace_candidate_limit 必须大于 0")
        if self.log_max_entries < 1:
            raise ValueError("log_max_entries 必须大于 0")
