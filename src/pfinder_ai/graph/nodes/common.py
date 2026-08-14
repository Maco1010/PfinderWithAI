"""多个调查节点共享的审计辅助函数。"""

from pfinder_ai.domain.errors import PfinderAIError
from pfinder_ai.domain.models import InvestigationErrorRecord, NextHop
from pfinder_ai.graph.state import InvestigationState


def make_step_id(state: InvestigationState, step_name: str) -> str:
    """使用调查、目标、深度和调用序号构造稳定步骤编号。"""

    target = state.get("current_target")
    target_id = target.target_id if target is not None else "root"
    investigation_id = state.get("investigation_id", "unknown")
    depth = state.get("investigation_depth", 0)
    call_count = state.get("provider_call_count", 0)
    return f"{investigation_id}:{step_name}:{depth}:{call_count}:{target_id}"


def make_error_record(
    state: InvestigationState,
    step_name: str,
    error: PfinderAIError,
) -> InvestigationErrorRecord:
    """将标准异常转换为只包含安全摘要的状态记录。"""

    previous_attempts = sum(
        1 for item in state.get("errors", ()) if item.step_name == step_name
    )
    safe_context = {
        str(key): str(value)[:200]
        for key, value in error.context.items()
    }
    return InvestigationErrorRecord(
        kind=error.kind,
        message=str(error),
        step_name=step_name,
        retryable=error.retryable,
        attempt=previous_attempts + 1,
        context=safe_context,
    )


def merge_text_values(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    """在节点内部合并少量文本，同时保留第一次出现的顺序。"""

    merged = list(left)
    for item in right:
        if item not in merged:
            merged.append(item)
    return tuple(merged)


def next_hop_id(next_hop: NextHop) -> str:
    """根据目标系统和发现证据生成稳定的 Trace 外依赖编号。"""

    return (
        f"{next_hop.target_system.casefold()}:"
        f"{next_hop.discovered_by_evidence_id}"
    )
