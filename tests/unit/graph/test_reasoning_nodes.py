"""代码调查、验证、决策、NextHop 和结果节点测试。"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from pfinder_ai.domain.enums import (
    ConclusionStatus,
    EvidenceSource,
    ExecutionStatus,
    NextAction,
    TargetSource,
    VerificationStatus,
)
from pfinder_ai.domain.models import (
    DiagnosisResult,
    Evidence,
    Hypothesis,
    IncidentInput,
    InvestigationStep,
    InvestigationTarget,
    NextHop,
    SystemContext,
)
from pfinder_ai.graph.nodes.code_investigator import CodeInvestigatorNode
from pfinder_ai.graph.nodes.decision_router import DecisionRouterNode
from pfinder_ai.graph.nodes.next_hop import EnqueueNextHopsNode
from pfinder_ai.graph.nodes.result_builder import ResultBuilderNode
from pfinder_ai.graph.nodes.result_persister import ResultPersisterNode
from pfinder_ai.graph.nodes.verifier import VerifierNode
from pfinder_ai.graph.policy import GraphExecutionPolicy
from pfinder_ai.graph.state import InvestigationState
from pfinder_ai.ports.code_analysis import (
    CodeInvestigationRequest,
    CodeInvestigationResult,
    SupplementalEvidenceRequest,
)
from pfinder_ai.ports.repository import RepositoryRequest, WorkspaceHandle
from pfinder_ai.services.verification import HypothesisVerifier
from pfinder_ai.services.workspace_manager import GitWorkspaceManager


class StubRepositoryAdapter:
    """在测试目录中准备一个最小合成仓库。"""

    def __init__(self) -> None:
        self.released = False
        self.workspace_path: Path | None = None

    async def materialize(
        self,
        request: RepositoryRequest,
        destination: Path,
    ) -> WorkspaceHandle:
        """写入不含真实代码的合成文件。"""

        (destination / "service.py").write_text(
            "raise TimeoutError('synthetic')",
            encoding="utf-8",
        )
        self.workspace_path = destination
        return WorkspaceHandle(
            path=destination,
            repository_url=request.repository_url,
            requested_revision=request.requested_revision,
            resolved_commit="b" * 40,
            revision_is_assumption=request.revision_is_assumption,
        )

    async def release(self, workspace: WorkspaceHandle) -> None:
        """记录释放动作，由 Manager 负责删除目录。"""

        self.released = True


class StubCodeAnalysisProvider:
    """返回相互引用的代码证据和根因候选。"""

    async def investigate(
        self,
        request: CodeInvestigationRequest,
    ) -> CodeInvestigationResult:
        """确认受控工作区存在后返回合成结果。"""

        assert (request.workspace.path / "service.py").exists()
        evidence = Evidence(
            evidence_id="code:synthetic:1",
            source=EvidenceSource.CODE,
            summary="超时异常未被转换为可重试结果",
            locator=(
                f"commit={request.workspace.resolved_commit};"
                "path=service.py;line=1"
            ),
            system=request.target.system,
        )
        hypothesis = Hypothesis(
            hypothesis_id="hypothesis:synthetic:1",
            statement="服务未处理下游超时，导致订单创建失败",
            target_system=request.target.system,
            confidence=0.9,
            supporting_evidence_ids=("log:synthetic:1", evidence.evidence_id),
        )
        return CodeInvestigationResult(
            evidence=(evidence,),
            hypotheses=(hypothesis,),
        )


class StubInvestigationStore:
    """只在内存中保存最终结果的调查存储替身。"""

    def __init__(self) -> None:
        self.result: DiagnosisResult | None = None

    async def append_step(
        self,
        investigation_id: str,
        step: InvestigationStep,
    ) -> None:
        """测试不单独持久化步骤。"""

        del investigation_id, step

    async def list_steps(self, investigation_id: str) -> tuple[InvestigationStep, ...]:
        """返回空的合成步骤列表。"""

        del investigation_id
        return ()

    async def save_result(
        self,
        investigation_id: str,
        result: DiagnosisResult,
    ) -> None:
        """保存调用方提供的结构化结果。"""

        del investigation_id
        self.result = result

    async def load_result(self, investigation_id: str) -> DiagnosisResult | None:
        """返回最近保存的结果。"""

        del investigation_id
        return self.result


def _base_state() -> InvestigationState:
    """创建代码调查节点所需的合成状态。"""

    target = InvestigationTarget(
        target_id="trace-synthetic:span-error",
        system="system-b",
        source=TargetSource.TRACE_CANDIDATE,
        reason="Span 显式异常",
        priority=0,
        trace_id="trace-synthetic",
        span_id="span-error",
    )
    return InvestigationState(
        investigation_id="investigation-1",
        incident=IncidentInput(
            description="合成订单创建失败",
            start_system="system-a",
            trace_id="trace-synthetic",
        ),
        current_target=target,
        current_context=SystemContext(
            system="system-b",
            repository_url="https://git.example.local/system-b.git",
            revision="release-synthetic",
        ),
        target_queue=(target,),
        visited_target_ids=(target.target_id,),
        evidence=(
            Evidence(
                evidence_id="log:synthetic:1",
                source=EvidenceSource.LOG,
                summary="订单调用记录下游超时",
                locator="synthetic-log:1",
                system="system-b",
            ),
        ),
        investigation_depth=1,
        provider_call_count=0,
        started_at=datetime.now(UTC),
        execution_status=ExecutionStatus.RUNNING,
    )


def test_code_verification_decision_and_result_flow(tmp_path: Path) -> None:
    """日志和代码相互印证后形成静态验证通过的结构化结果。"""

    state = _base_state()
    repository = StubRepositoryAdapter()
    code_node = CodeInvestigatorNode(
        StubCodeAnalysisProvider(),
        GitWorkspaceManager(
            repository,
            trusted_hosts=frozenset({"git.example.local"}),
            base_directory=tmp_path,
        ),
    )
    code_update = asyncio.run(code_node(state))

    assert repository.released is True
    assert repository.workspace_path is not None
    assert not repository.workspace_path.exists()

    verification_state = InvestigationState(
        **{
            **state,
            "evidence": state["evidence"] + code_update["evidence"],
            "hypotheses": code_update["hypotheses"],
            "current_hypothesis": code_update["current_hypothesis"],
        }
    )
    verification_update = VerifierNode(HypothesisVerifier())(verification_state)
    assert verification_update["verification"].status is VerificationStatus.PASSED

    decision_state = InvestigationState(
        **verification_state,
        verification=verification_update["verification"],
        next_action=verification_update["next_action"],
    )
    decision_update = DecisionRouterNode(
        GraphExecutionPolicy(max_depth=4, max_provider_calls=20)
    )(decision_state)
    assert decision_update["next_action"] is NextAction.FINISH
    assert decision_update["termination_reason"] is not None

    result_state = InvestigationState(
        **decision_state,
        termination_reason=decision_update["termination_reason"],
    )
    result = ResultBuilderNode()(result_state)["result"]
    assert result is not None
    assert result.conclusion_status is ConclusionStatus.VERIFIED
    assert result.execution_status is ExecutionStatus.COMPLETED
    assert "未执行运行时验证" in result.summary


def test_next_hop_is_enqueued_once() -> None:
    """Trace 外依赖使用稳定编号入队，重复执行不会生成不同目标。"""

    state = _base_state()
    next_hop = NextHop(
        target_system="system-d",
        reason="代码发现异步消息消费者",
        discovered_by_evidence_id="code:synthetic:1",
        search_context={"operation": "consume_order_event"},
    )
    first = EnqueueNextHopsNode()(
        InvestigationState(**state, next_hops=(next_hop,))
    )
    second = EnqueueNextHopsNode()(
        InvestigationState(
            **state,
            next_hops=(next_hop,),
            enqueued_next_hop_ids=first["enqueued_next_hop_ids"],
        )
    )

    assert first["target_queue"][0].source is TargetSource.DISCOVERED_DEPENDENCY
    assert second["target_queue"] == ()


def test_decision_router_stops_before_unbounded_loop() -> None:
    """需要更多代码时，达到深度上限会覆盖继续调查动作。"""

    state = _base_state()
    state["next_action"] = NextAction.INVESTIGATE_CODE
    update = DecisionRouterNode(
        GraphExecutionPolicy(max_depth=1, max_provider_calls=20)
    )(state)

    assert update["next_action"] is NextAction.FINISH
    assert update["termination_reason"] == "达到最大调查深度"


def test_result_persister_saves_enriched_result() -> None:
    """最终存储包含持久化步骤，且不会混同为 LangGraph 检查点。"""

    state = _base_state()
    unresolved_result = ResultBuilderNode()(state)["result"]
    assert unresolved_result is not None
    store = StubInvestigationStore()
    update = asyncio.run(
        ResultPersisterNode(store)(
            InvestigationState(**state, result=unresolved_result)
        )
    )

    assert store.result is not None
    assert store.result.investigation_steps[-1].name == "persist_result"
    assert update["result"] == store.result


def test_verifier_prioritizes_requested_logs_without_hypothesis() -> None:
    """代码调查明确请求日志时，Verifier 不应直接跳到其他系统。"""

    state = _base_state()
    state["pending_requests"] = (
        SupplementalEvidenceRequest(
            action=NextAction.GATHER_LOGS,
            reason="需要确认超时前的重试次数",
            search_hints=("retry_count",),
        ),
    )
    update = VerifierNode(HypothesisVerifier())(state)

    assert update["next_action"] is NextAction.GATHER_LOGS
