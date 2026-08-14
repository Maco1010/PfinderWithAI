"""不依赖 LLM 的 Trace 候选筛选基线。"""

from dataclasses import dataclass

from pfinder_ai.domain.enums import EvidenceSource, TargetSource
from pfinder_ai.domain.models import Evidence, InvestigationTarget, TraceCandidate, TraceSpan


@dataclass(frozen=True, slots=True)
class TraceAnalysisResult:
    """TraceAnalyser 输出的有序调查目标和对应证据。"""

    targets: tuple[InvestigationTarget, ...]
    evidence: tuple[Evidence, ...]


class TraceAnalysisService:
    """使用可解释的确定性规则生成候选调查目标。

    该基线不会判断根因，只负责把错误 Span 和高耗时 Span 转换为有序
    候选。后续可以在存在歧义时，通过 LLMProvider 增强排序。
    """

    _NORMAL_STATUSES = frozenset({"ok", "success", "unset"})

    def __init__(self, *, max_targets: int = 5) -> None:
        if max_targets < 1:
            raise ValueError("max_targets 必须大于 0")
        self._max_targets = max_targets

    def analyse(self, candidates: tuple[TraceCandidate, ...]) -> TraceAnalysisResult:
        """按 Trace 匹配度、异常状态和耗时生成去重后的候选队列。"""

        targets: list[InvestigationTarget] = []
        evidence: list[Evidence] = []
        seen_spans: set[tuple[str, str]] = set()

        for candidate in sorted(candidates, key=lambda item: item.match_score, reverse=True):
            ranked_spans = sorted(
                candidate.spans,
                key=lambda span: (not self._is_anomalous(span), -span.duration_ms),
            )
            anomalous_spans = [span for span in ranked_spans if self._is_anomalous(span)]

            # 如果 Trace 没有显式错误，保留最慢 Span 作为低优先级调查入口，
            # 但不能把它表述为已经确认的根因。
            selected_spans = anomalous_spans or ranked_spans[:1]
            for span in selected_spans:
                dedup_key = (candidate.trace_id, span.span_id)
                if dedup_key in seen_spans:
                    continue
                seen_spans.add(dedup_key)

                priority = len(targets)
                reason = self._target_reason(span)
                target_id = f"{candidate.trace_id}:{span.span_id}"
                evidence_id = f"trace:{candidate.trace_id}:{span.span_id}"

                targets.append(
                    InvestigationTarget(
                        target_id=target_id,
                        system=span.system,
                        source=TargetSource.TRACE_CANDIDATE,
                        reason=reason,
                        priority=priority,
                        trace_id=candidate.trace_id,
                        operation=span.operation,
                        span_id=span.span_id,
                    )
                )
                evidence.append(
                    Evidence(
                        evidence_id=evidence_id,
                        source=EvidenceSource.TRACE,
                        system=span.system,
                        summary=(
                            f"Span {span.operation} 状态为 {span.status}，"
                            f"耗时 {span.duration_ms:.0f}ms。"
                        ),
                        locator=(
                            f"trace_id={candidate.trace_id};span_id={span.span_id}"
                        ),
                        attributes={
                            "operation": span.operation,
                            "status": span.status,
                            "match_reason": candidate.match_reason,
                        },
                    )
                )

                if len(targets) >= self._max_targets:
                    return TraceAnalysisResult(tuple(targets), tuple(evidence))

        return TraceAnalysisResult(tuple(targets), tuple(evidence))

    def _is_anomalous(self, span: TraceSpan) -> bool:
        """判断 Span 是否包含明确异常信号。"""

        return span.status.casefold() not in self._NORMAL_STATUSES or bool(span.error_summary)

    def _target_reason(self, span: TraceSpan) -> str:
        """生成可直接展示和审计的候选排序原因。"""

        if span.error_summary:
            return f"Span 包含异常：{span.error_summary}"
        if self._is_anomalous(span):
            return f"Span 状态异常：{span.status}"
        return "Trace 未包含显式错误，选择最高耗时 Span 作为调查入口"
