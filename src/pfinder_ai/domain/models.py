"""证据驱动故障调查使用的核心数据契约。

这些模型只保存摘要和来源定位，不保存原始生产数据。任何 Provider 专用
响应都必须先转换为这些类型，才能进入 LangGraph State 或 InvestigationStore。
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
    """跨流程步骤传递的严格、不可变领域模型基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class TimeRange(DomainModel):
    """日志和 Trace 查询使用的精确时间范围或自然语言时间描述。"""

    start: datetime | None = None
    end: datetime | None = None
    description: str | None = None

    @model_validator(mode="after")
    def validate_order(self) -> "TimeRange":
        """拒绝起止时间倒置，同时允许只提供模糊时间描述。"""

        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("time range start must not be after end")
        return self


class IncidentInput(DomainModel):
    """ClueExtractor 生成的标准化问题输入。"""

    description: str = Field(min_length=1)
    business_keys: dict[str, str] = Field(default_factory=dict)
    start_system: str | None = None
    trace_id: str | None = None
    time_range: TimeRange | None = None
    missing_fields: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()


class SystemContext(DomainModel):
    """用于访问目标系统各类证据源的确定性元数据。"""

    system: str = Field(min_length=1)
    repository_url: str | None = None
    revision: str | None = None
    log_source: str | None = None
    trace_service: str | None = None
    source_locator: str | None = None
    revision_is_assumption: bool = False


class TraceSpan(DomainModel):
    """与 Provider 无关的待调查 Span 摘要。"""

    span_id: str = Field(min_length=1)
    parent_span_id: str | None = None
    system: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    duration_ms: float = Field(ge=0)
    status: str = Field(min_length=1)
    error_summary: str | None = None


class TraceCandidate(DomainModel):
    """候选请求 Trace，以及解释其相关性的匹配分数。"""

    trace_id: str = Field(min_length=1)
    match_score: float = Field(ge=0, le=1)
    spans: tuple[TraceSpan, ...] = ()
    match_reason: str = Field(min_length=1)


class InvestigationTarget(DomainModel):
    """等待收集证据的系统或依赖目标。"""

    target_id: str = Field(min_length=1)
    system: str = Field(min_length=1)
    source: TargetSource
    reason: str = Field(min_length=1)
    priority: int = Field(ge=0)
    operation: str | None = None
    span_id: str | None = None


class Evidence(DomainModel):
    """已经脱敏且包含足够来源定位、可以复核的事实。"""

    evidence_id: str = Field(min_length=1)
    source: EvidenceSource
    summary: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    system: str | None = None
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    redacted: bool = True
    attributes: dict[str, str] = Field(default_factory=dict)


class Hypothesis(DomainModel):
    """关联明确证据、可以被证伪的根因候选。"""

    hypothesis_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    target_system: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    supporting_evidence_ids: tuple[str, ...] = ()
    conflicting_evidence_ids: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()


class VerificationResult(DomainModel):
    """使用 Trace、日志和代码证据验证根因假设的结果。"""

    status: VerificationStatus
    summary: str = Field(min_length=1)
    supporting_evidence_ids: tuple[str, ...] = ()
    conflicting_evidence_ids: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    next_action: NextAction
    runtime_verified: bool = False


class NextHop(DomainModel):
    """在当前 Trace 候选队列之外新发现的依赖。"""

    target_system: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    discovered_by_evidence_id: str = Field(min_length=1)
    search_context: dict[str, str] = Field(default_factory=dict)


class InvestigationErrorRecord(DomainModel):
    """可安全写入检查点和审计轨迹的错误信息。"""

    kind: ErrorKind
    message: str = Field(min_length=1)
    step_name: str = Field(min_length=1)
    retryable: bool
    attempt: int = Field(ge=1)
    context: dict[str, str] = Field(default_factory=dict)


class UsageRecord(DomainModel):
    """单次 Provider 操作产生的非敏感用量信息。"""

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
    """附加到诊断结果的聚合用量，不包含原始请求。"""

    calls: int = Field(default=0, ge=0)
    duration_ms: float = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None


class InvestigationStep(DomainModel):
    """一次查询、发现、判断和后续动作组成的可审计记录。"""

    step_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    target_system: str | None = None
    query_summary: str | None = None
    evidence_ids: tuple[str, ...] = ()
    decision: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    next_action: NextAction | None = None


class DiagnosisResult(DomainModel):
    """面向用户的最终诊断及其完整证据轨迹。"""

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
