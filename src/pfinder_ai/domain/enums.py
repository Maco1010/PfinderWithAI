"""领域模型与流程路由共享的枚举。"""

from enum import StrEnum


class EvidenceSource(StrEnum):
    """用于支持或否定根因假设的证据来源。"""

    TRACE = "trace"
    LOG = "log"
    CODE = "code"
    TOOL = "tool"


class TargetSource(StrEnum):
    """调查目标进入有序候选队列的来源。"""

    START_SYSTEM = "start_system"
    TRACE_CANDIDATE = "trace_candidate"
    DISCOVERED_DEPENDENCY = "discovered_dependency"


class VerificationStatus(StrEnum):
    """使用现有证据验证根因假设后的结果。"""

    PASSED = "passed"
    NEEDS_EVIDENCE = "needs_evidence"
    REJECTED = "rejected"


class ConclusionStatus(StrEnum):
    """最终诊断向用户展示的证据充分程度。"""

    VERIFIED = "verified"
    SUPPORTED_HYPOTHESIS = "supported_hypothesis"
    UNRESOLVED = "unresolved"


class ExecutionStatus(StrEnum):
    """工作流执行状态，与诊断结论是否充分相互独立。"""

    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"


class NextAction(StrEnum):
    """验证结束后，决策路由可以请求的后续动作。"""

    GATHER_LOGS = "gather_logs"
    INVESTIGATE_CODE = "investigate_code"
    SELECT_TRACE_CANDIDATE = "select_trace_candidate"
    INVESTIGATE_DISCOVERED_DEPENDENCY = "investigate_discovered_dependency"
    FINISH = "finish"


class ErrorKind(StrEnum):
    """重试和降级策略使用的稳定错误分类。"""

    INVALID_INPUT = "invalid_input"
    TRANSIENT = "transient"
    UNAUTHORIZED = "unauthorized"
    NOT_FOUND = "not_found"
    INVALID_RESPONSE = "invalid_response"
    BUDGET_EXCEEDED = "budget_exceeded"
    INTERNAL = "internal"
