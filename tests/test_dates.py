"""Tests for date-only handling."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from twcaldav.dates import date_to_datetime, ical_dates, local_timezone

BERLIN = ZoneInfo("Europe/Berlin")


class TestDateToDatetime:
    """Tests for reading a date-only value as local midnight."""

    def test_summer_date_is_local_midnight(self) -> None:
        """A summer date is midnight CEST, 22:00 UTC the day before."""
        value = date_to_datetime(date(2025, 8, 15), BERLIN)

        assert value == datetime(2025, 8, 14, 22, 0, tzinfo=UTC)

    def test_winter_date_is_local_midnight(self) -> None:
        """A winter date is midnight CET, 23:00 UTC the day before."""
        value = date_to_datetime(date(2025, 12, 1), BERLIN)

        assert value == datetime(2025, 11, 30, 23, 0, tzinfo=UTC)

    def test_utc_date_is_utc_midnight(self) -> None:
        """With UTC, a date stays midnight UTC as before."""
        value = date_to_datetime(date(2025, 8, 15), UTC)

        assert value == datetime(2025, 8, 15, 0, 0, tzinfo=UTC)


class TestIcalDates:
    """Tests for writing local-midnight values as dates."""

    def test_local_midnight_becomes_date(self) -> None:
        """A due at local midnight is written as a date."""
        due = datetime(2025, 8, 14, 22, 0, tzinfo=UTC)

        assert ical_dates(due, None, BERLIN) == (date(2025, 8, 15), None)

    def test_other_time_stays_datetime(self) -> None:
        """A due at 09:00 local stays a datetime."""
        due = datetime(2025, 8, 15, 7, 0, tzinfo=UTC)

        assert ical_dates(due, None, BERLIN) == (due, None)

    def test_both_at_midnight_become_dates(self) -> None:
        """Due and start both at local midnight are both written as dates."""
        due = datetime(2025, 8, 14, 22, 0, tzinfo=UTC)
        start = datetime(2025, 8, 9, 22, 0, tzinfo=UTC)

        assert ical_dates(due, start, BERLIN) == (date(2025, 8, 15), date(2025, 8, 10))

    def test_mixed_pair_stays_datetimes(self) -> None:
        """DUE and DTSTART must share a value type, so a timed start keeps both."""
        due = datetime(2025, 8, 14, 22, 0, tzinfo=UTC)
        start = datetime(2025, 8, 10, 7, 0, tzinfo=UTC)

        assert ical_dates(due, start, BERLIN) == (due, start)

    def test_naive_midnight_is_utc(self) -> None:
        """A naive value is UTC, so naive midnight is not Berlin midnight."""
        due = datetime(2025, 8, 15, 0, 0)

        assert ical_dates(due, None, BERLIN) == (due, None)

    def test_nothing_set(self) -> None:
        """No values gives no values."""
        assert ical_dates(None, None, BERLIN) == (None, None)


class TestLocalTimezone:
    """Tests for finding the system timezone."""

    def test_uses_tz_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TZ wins over /etc/localtime."""
        monkeypatch.setenv("TZ", "Asia/Tashkent")

        assert local_timezone() == ZoneInfo("Asia/Tashkent")

    def test_invalid_tz_variable_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unknown TZ name does not crash."""
        monkeypatch.setenv("TZ", "Nowhere/Nothing")

        assert local_timezone() is not None
