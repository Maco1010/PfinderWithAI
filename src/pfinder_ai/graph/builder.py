"""装配 PfinderWithAI 主调查 StateGraph。"""

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer

from pfinder_ai.graph.dependencies import GraphDependencies
from pfinder_ai.graph.nodes.clue_extractor import ClueExtractorNode
from pfinder_ai.graph.nodes.code_investigator import CodeInvestigatorNode
from pfinder_ai.graph.nodes.context_resolver import ContextResolverNode
from pfinder_ai.graph.nodes.decision_router import DecisionRouterNode
from pfinder_ai.graph.nodes.log_parser import LogParserNode
from pfinder_ai.graph.nodes.next_hop import EnqueueNextHopsNode
from pfinder_ai.graph.nodes.result_builder import ResultBuilderNode
from pfinder_ai.graph.nodes.result_persister import ResultPersisterNode
from pfinder_ai.graph.nodes.target_selector import TargetSelectorNode
from pfinder_ai.graph.nodes.trace_analyser import TraceAnalyserNode
from pfinder_ai.graph.nodes.trace_finder import TraceFinderNode
from pfinder_ai.graph.nodes.verifier import VerifierNode
from pfinder_ai.graph.routing import (
    route_after_clue_extraction,
    route_after_decision,
    route_after_log_collection,
    route_after_start_context,
    route_after_target_context,
    route_after_target_selection,
)
from pfinder_ai.graph.state import InvestigationState

type InvestigationGraph = CompiledStateGraph[
    InvestigationState,
    None,
    InvestigationState,
    InvestigationState,
]


def build_investigation_graph(
    dependencies: GraphDependencies,
    *,
    checkpointer: Checkpointer = None,
) -> InvestigationGraph:
    """构建一个主 Agent 图，并通过 Provider 委派所有外部能力。"""

    clue_extractor = ClueExtractorNode(dependencies.llm)
    context_resolver = ContextResolverNode(dependencies.metadata)
    trace_finder = TraceFinderNode(
        dependencies.traces,
        candidate_limit=dependencies.trace_candidate_limit,
    )
    trace_analyser = TraceAnalyserNode(dependencies.trace_analyser)
    target_selector = TargetSelectorNode()
    log_parser = LogParserNode(
        dependencies.logs,
        max_entries=dependencies.log_max_entries,
    )
    code_investigator = CodeInvestigatorNode(
        dependencies.code_analysis,
        dependencies.workspaces,
    )
    verifier = VerifierNode(dependencies.hypothesis_verifier)
    decision_router = DecisionRouterNode(dependencies.policy)
    enqueue_next_hops = EnqueueNextHopsNode()
    result_builder = ResultBuilderNode()
    result_persister = ResultPersisterNode(dependencies.store)

    graph: StateGraph[
        InvestigationState,
        None,
        InvestigationState,
        InvestigationState,
    ] = StateGraph(InvestigationState)
    graph.add_node("clue_extractor", clue_extractor.__call__)
    graph.add_node("resolve_start_context", context_resolver.resolve_start)
    graph.add_node("find_trace", trace_finder.__call__)
    graph.add_node("analyse_trace", trace_analyser.__call__)
    graph.add_node("select_target", target_selector.__call__)
    graph.add_node("resolve_target_context", context_resolver.resolve_target)
    graph.add_node("gather_logs", log_parser.__call__)
    graph.add_node("investigate_code", code_investigator.__call__)
    graph.add_node("verify_hypothesis", verifier.__call__)
    graph.add_node("decision_router", decision_router.__call__)
    graph.add_node("enqueue_next_hops", enqueue_next_hops.__call__)
    graph.add_node("build_result", result_builder.__call__)
    graph.add_node("persist_result", result_persister.__call__)

    graph.add_edge(START, "clue_extractor")
    graph.add_conditional_edges(
        "clue_extractor",
        route_after_clue_extraction,
        {
            "resolve_start_context": "resolve_start_context",
            "build_result": "build_result",
        },
    )
    graph.add_conditional_edges(
        "resolve_start_context",
        route_after_start_context,
        {
            "find_trace": "find_trace",
            "build_result": "build_result",
        },
    )
    graph.add_edge("find_trace", "analyse_trace")
    graph.add_edge("analyse_trace", "select_target")
    graph.add_conditional_edges(
        "select_target",
        route_after_target_selection,
        {
            "resolve_target_context": "resolve_target_context",
            "build_result": "build_result",
        },
    )
    graph.add_conditional_edges(
        "resolve_target_context",
        route_after_target_context,
        {
            "gather_logs": "gather_logs",
            "select_target": "select_target",
            "build_result": "build_result",
        },
    )
    graph.add_conditional_edges(
        "gather_logs",
        route_after_log_collection,
        {
            "investigate_code": "investigate_code",
            "decision_router": "decision_router",
        },
    )
    graph.add_edge("investigate_code", "verify_hypothesis")
    graph.add_edge("verify_hypothesis", "decision_router")
    graph.add_conditional_edges(
        "decision_router",
        route_after_decision,
        {
            "gather_logs": "gather_logs",
            "investigate_code": "investigate_code",
            "select_target": "select_target",
            "enqueue_next_hops": "enqueue_next_hops",
            "build_result": "build_result",
        },
    )
    graph.add_edge("enqueue_next_hops", "select_target")
    graph.add_edge("build_result", "persist_result")
    graph.add_edge("persist_result", END)

    return graph.compile(
        checkpointer=checkpointer,
        name="pfinder_with_ai_investigation",
    )
