"""TraceAnalysisService 的确定性排序测试。"""

from pfinder_ai.domain.enums import TargetSource
from pfinder_ai.domain.models import TraceCandidate, TraceSpan
from pfinder_ai.services.trace_analysis import TraceAnalysisService


def test_anomalous_span_is_selected_before_slow_success_span() -> None:
    """显式异常应优先于仅耗时较高但成功的 Span。"""

    candidate = TraceCandidate(
        trace_id="trace-001",
        match_score=0.9,
        match_reason="业务 Key 和时间范围匹配",
        spans=(
            TraceSpan(
                span_id="span-success",
                system="system-c",
                operation="validate",
                duration_ms=900,
                status="ok",
            ),
            TraceSpan(
                span_id="span-error",
                system="system-d",
                operation="trade",
                duration_ms=300,
                status="error",
                error_summary="upstream timeout",
            ),
        ),
    )

    result = TraceAnalysisService().analyse((candidate,))

    assert result.targets[0].system == "system-d"
    assert result.targets[0].source is TargetSource.TRACE_CANDIDATE
    assert result.targets[0].trace_id == "trace-001"
    assert result.evidence[0].locator == "trace_id=trace-001;span_id=span-error"
