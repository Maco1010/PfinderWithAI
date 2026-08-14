"""LangGraph 主调查图的拓扑装配测试。"""

from typing import cast

from pfinder_ai.graph.builder import build_investigation_graph
from pfinder_ai.graph.dependencies import GraphDependencies
from pfinder_ai.graph.policy import GraphExecutionPolicy
from pfinder_ai.ports.code_analysis import CodeAnalysisProvider
from pfinder_ai.ports.logs import LogProvider
from pfinder_ai.ports.metadata import MetadataProvider
from pfinder_ai.ports.stores import InvestigationStore
from pfinder_ai.ports.trace import TraceProvider
from pfinder_ai.services.workspace_manager import GitWorkspaceManager


def test_builder_contains_required_investigation_nodes() -> None:
    """图必须包含从线索提取到结果持久化的完整主链路。"""

    placeholder = object()
    dependencies = GraphDependencies(
        metadata=cast(MetadataProvider, placeholder),
        traces=cast(TraceProvider, placeholder),
        logs=cast(LogProvider, placeholder),
        code_analysis=cast(CodeAnalysisProvider, placeholder),
        workspaces=cast(GitWorkspaceManager, placeholder),
        store=cast(InvestigationStore, placeholder),
        policy=GraphExecutionPolicy(max_depth=4, max_provider_calls=20),
    )

    graph = build_investigation_graph(dependencies)
    node_names = set(graph.get_graph().nodes)

    assert {
        "clue_extractor",
        "resolve_start_context",
        "find_trace",
        "analyse_trace",
        "select_target",
        "resolve_target_context",
        "gather_logs",
        "investigate_code",
        "verify_hypothesis",
        "decision_router",
        "enqueue_next_hops",
        "build_result",
        "persist_result",
    }.issubset(node_names)
