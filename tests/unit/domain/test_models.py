"""验证领域边界强制执行的数据不变量。"""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from pfinder_ai.domain.enums import TargetSource
from pfinder_ai.domain.models import InvestigationTarget, TimeRange


def test_time_range_rejects_inverted_exact_range() -> None:
    """拒绝可能导致错误日志查询的倒置时间范围。"""

    end = datetime.now(UTC)
    with pytest.raises(ValidationError):
        TimeRange(start=end + timedelta(minutes=1), end=end)


def test_investigation_target_records_candidate_source() -> None:
    """候选目标必须记录来源，避免把普通候选切换误写为 NextHop。"""

    target = InvestigationTarget(
        target_id="trace-1:span-2",
        system="system-b",
        source=TargetSource.TRACE_CANDIDATE,
        reason="span returned an error",
        priority=0,
    )

    assert target.source is TargetSource.TRACE_CANDIDATE
