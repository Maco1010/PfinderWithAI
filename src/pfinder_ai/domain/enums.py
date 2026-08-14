"""Enumerations shared by domain models and workflow routing."""

from enum import StrEnum


class EvidenceSource(StrEnum):
    """Origin of a fact used to support or reject a hypothesis."""

    TRACE = "trace"
    LOG = "log"
    CODE = "code"
    TOOL = "tool"


class TargetSource(StrEnum):
    """How an investigation target entered the ordered target queue."""

    START_SYSTEM = "start_system"
    TRACE_CANDIDATE = "trace_candidate"
    DISCOVERED_DEPENDENCY = "discovered_dependency"


class VerificationStatus(StrEnum):
    """Outcome of checking a hypothesis against the available evidence."""

    PASSED = "passed"
    NEEDS_EVIDENCE = "needs_evidence"
    REJECTED = "rejected"


class ConclusionStatus(StrEnum):
    """Evidence strength exposed to users in the final diagnosis."""

    VERIFIED = "verified"
    SUPPORTED_HYPOTHESIS = "supported_hypothesis"
    UNRESOLVED = "unresolved"


class ExecutionStatus(StrEnum):
    """Lifecycle status of the workflow, independent of diagnosis quality."""

    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"


class NextAction(StrEnum):
    """Actions the decision router can request after verification."""

    GATHER_LOGS = "gather_logs"
    INVESTIGATE_CODE = "investigate_code"
    SELECT_TRACE_CANDIDATE = "select_trace_candidate"
    INVESTIGATE_DISCOVERED_DEPENDENCY = "investigate_discovered_dependency"
    FINISH = "finish"


class ErrorKind(StrEnum):
    """Stable error categories used by retry and degradation policies."""

    INVALID_INPUT = "invalid_input"
    TRANSIENT = "transient"
    UNAUTHORIZED = "unauthorized"
    NOT_FOUND = "not_found"
    INVALID_RESPONSE = "invalid_response"
    BUDGET_EXCEEDED = "budget_exceeded"
    INTERNAL = "internal"

