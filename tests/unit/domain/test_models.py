"""Unit tests for invariants enforced at the domain boundary."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from pfinder_ai.domain.enums import TargetSource
from pfinder_ai.domain.models import InvestigationTarget, TimeRange


def test_time_range_rejects_inverted_exact_range() -> None:
    """An inverted range would otherwise produce misleading log queries."""

    end = datetime.now(UTC)
    with pytest.raises(ValidationError):
        TimeRange(start=end + timedelta(minutes=1), end=end)


def test_investigation_target_records_candidate_source() -> None:
    """A queue target records its origin so NextHop is not used ambiguously."""

    target = InvestigationTarget(
        target_id="trace-1:span-2",
        system="system-b",
        source=TargetSource.TRACE_CANDIDATE,
        reason="span returned an error",
        priority=0,
    )

    assert target.source is TargetSource.TRACE_CANDIDATE
