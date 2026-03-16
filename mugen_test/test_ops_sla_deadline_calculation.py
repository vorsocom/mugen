"""Unit tests for ops_sla business-hours deadline calculations."""

from datetime import datetime, time, timezone
import unittest
from unittest.mock import Mock

from mugen.core.plugin.ops_sla.domain import SlaCalendarDE
from mugen.core.plugin.ops_sla.service.sla_clock import SlaClockService


class TestOpsSlaDeadlineCalculation(unittest.TestCase):
    """Tests weekend/holiday boundary handling in SLA calendar math."""

    def test_rolls_over_weekend(self) -> None:
        svc = SlaClockService(table="ops_sla_clock", rsg=Mock())

        calendar = SlaCalendarDE(
            timezone="UTC",
            business_start_time=time(9, 0),
            business_end_time=time(17, 0),
            business_days=[1, 2, 3, 4, 5],
            holiday_refs=[],
        )

        start = datetime(2026, 2, 13, 16, 30, tzinfo=timezone.utc)  # Friday
        deadline = svc._add_business_seconds(
            start_at=start,
            seconds=2 * 60 * 60,
            calendar=calendar,
        )

        self.assertEqual(
            deadline,
            datetime(2026, 2, 16, 10, 30, tzinfo=timezone.utc),  # Monday
        )

    def test_rolls_over_holiday(self) -> None:
        svc = SlaClockService(table="ops_sla_clock", rsg=Mock())

        calendar = SlaCalendarDE(
            timezone="UTC",
            business_start_time=time(9, 0),
            business_end_time=time(17, 0),
            business_days=[1, 2, 3, 4, 5],
            holiday_refs=["2026-02-16"],  # Monday holiday
        )

        start = datetime(2026, 2, 13, 16, 30, tzinfo=timezone.utc)  # Friday
        deadline = svc._add_business_seconds(
            start_at=start,
            seconds=2 * 60 * 60,
            calendar=calendar,
        )

        self.assertEqual(
            deadline,
            datetime(2026, 2, 17, 10, 30, tzinfo=timezone.utc),  # Tuesday
        )
