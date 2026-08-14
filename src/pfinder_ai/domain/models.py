"""Core data contracts for evidence-driven incident investigation.

These models intentionally store summaries and source locators instead of raw
production payloads. Provider-specific responses are converted into these
types before entering the LangGraph state or InvestigationStore.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pfinder_ai.domain.enums import (
    ConclusionStatus,
    ErrorKind,
    EvidenceSource,
    ExecutionStatus,
    NextAction,
    TargetSource,
    VerificationStatus,
)


class DomainModel(BaseModel):
    """Strict immutable base class for values shared across workflow steps."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class TimeRange(DomainModel):
    """Optional exact or human-provided time window for log and trace queries."""

    start: datetime | None = None
    end: datetime | None = None
    description: str | None = None

    @model_validator(mode="after")
    def validate_order(self) -> "TimeRange":
        """Reject inverted exact ranges while allowing approximate text input."""

        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("time range start must not be after end")
        return self


class IncidentInput(DomainModel):
    """Normalized problem statement produced by the clue extraction step."""

    description: str = Field(min_length=1)
    business_keys: dict[str, str] = Field(default_factory=dict)
    start_system: str | None = None
    trace_id: str | None = None
    time_range: TimeRange | None = None
    missing_fields: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()


class SystemContext(DomainModel):
    """Deterministic metadata used to reach a system's evidence sources."""

    system: str = Field(min_length=1)
    repository_url: str | None = None
    revision: str | None = None
    log_source: str | None = None
    trace_service: str | None = None
    source_locator: str | None = None
    revision_is_assumption: bool = False


class TraceSpan(DomainModel):
    """Provider-neutral summary of a span relevant to investigation."""

    span_id: str = Field(min_length=1)
    parent_span_id: str | None = None
    system: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    duration_ms: float = Field(ge=0)
    status: str = Field(min_length=1)
    error_summary: str | None = None


class TraceCandidate(DomainModel):
    """A possible request trace and the score explaining its relevance."""

    trace_id: str = Field(min_length=1)
    match_score: float = Field(ge=0, le=1)
    spans: tuple[TraceSpan, ...] = ()
    match_reason: str = Field(min_length=1)


class InvestigationTarget(DomainModel):
    """One system or dependency queued for evidence collection."""

    target_id: str = Field(min_length=1)
    system: str = Field(min_length=1)
    source: TargetSource
    reason: str = Field(min_length=1)
    priority: int = Field(ge=0)
    operation: str | None = None
    span_id: str | None = None


class Evidence(DomainModel):
    """Redacted fact with enough source information to reproduce the finding."""

    evidence_id: str = Field(min_length=1)
    source: EvidenceSource
    summary: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    system: str | None = None
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    redacted: bool = True
    attributes: dict[str, str] = Field(default_factory=dict)


class Hypothesis(DomainModel):
    """A falsifiable root-cause candidate linked to explicit evidence."""

    hypothesis_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    target_system: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    supporting_evidence_ids: tuple[str, ...] = ()
    conflicting_evidence_ids: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()


class VerificationResult(DomainModel):
    """Result of checking a hypothesis against trace, log, and code evidence."""

    status: VerificationStatus
    summary: str = Field(min_length=1)
    supporting_evidence_ids: tuple[str, ...] = ()
    conflicting_evidence_ids: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    next_action: NextAction
    runtime_verified: bool = False


class NextHop(DomainModel):
    """Dependency discovered outside the current trace candidate queue."""

    target_system: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    discovered_by_evidence_id: str = Field(min_length=1)
    search_context: dict[str, str] = Field(default_factory=dict)


class InvestigationErrorRecord(DomainModel):
    """Safe error details stored in checkpoints and audit history."""

    kind: ErrorKind
    message: str = Field(min_length=1)
    step_name: str = Field(min_length=1)
    retryable: bool
    attempt: int = Field(ge=1)
    context: dict[str, str] = Field(default_factory=dict)


class UsageRecord(DomainModel):
    """Non-sensitive usage metadata for one provider operation."""

    provider: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    duration_ms: float = Field(ge=0)
    success: bool
    retries: int = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class UsageSummary(DomainModel):
    """Aggregated usage attached to the diagnosis without raw requests."""

    calls: int = Field(default=0, ge=0)
    duration_ms: float = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None


class InvestigationStep(DomainModel):
    """Auditable record of one query, finding, decision, and next action."""

    step_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    target_system: str | None = None
    query_summary: str | None = None
    evidence_ids: tuple[str, ...] = ()
    decision: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    next_action: NextAction | None = None


class DiagnosisResult(DomainModel):
    """Final user-facing diagnosis and its complete evidence trail."""

    execution_status: ExecutionStatus
    conclusion_status: ConclusionStatus
    summary: str = Field(min_length=1)
    root_cause: str | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: tuple[Evidence, ...] = ()
    investigation_steps: tuple[InvestigationStep, ...] = ()
    verification: VerificationResult | None = None
    unresolved_questions: tuple[str, ...] = ()
    recommended_actions: tuple[str, ...] = ()
    termination_reason: str = Field(min_length=1)
    usage: UsageSummary = Field(default_factory=UsageSummary)

