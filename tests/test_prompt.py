from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from boxboxbox.models import Driver, RaceEvent
from boxboxbox.summariser.prompt import (
    _build_template_context,
    _driver_name,
    _format_lap_time,
    _format_time,
    _sort_gap,
    build_prompt,
)


def _make_driver(number: int, full_name: str, acronym: str, team: str = "Team") -> Driver:
    d = MagicMock(spec=Driver)
    d.driver_number = number
    d.full_name = full_name
    d.name_acronym = acronym
    d.team_name = team
    return d


DRIVER_MAP = {
    44: _make_driver(44, "Lewis HAMILTON", "HAM", "Ferrari"),
    63: _make_driver(63, "George RUSSELL", "RUS", "Mercedes"),
    12: _make_driver(12, "Andrea Kimi ANTONELLI", "ANT", "Mercedes"),
    16: _make_driver(16, "Charles LECLERC", "LEC", "Ferrari"),
    6: _make_driver(6, "Nico HULKENBERG", "HUL", "Sauber"),
}


class TestDriverName:
    def test_known_driver(self):
        assert _driver_name(DRIVER_MAP, 44) == "Lewis HAMILTON (HAM)"

    def test_unknown_driver(self):
        assert _driver_name(DRIVER_MAP, 999) == "#999"

    def test_none_driver(self):
        assert _driver_name(DRIVER_MAP, None) is None


class TestFormatTime:
    def test_iso_with_timezone(self):
        assert _format_time("2026-03-15T07:04:07.595000+00:00") == "07:04:07"

    def test_iso_without_timezone(self):
        assert _format_time("2026-03-15T07:04:07") == "07:04:07"

    def test_none(self):
        assert _format_time(None) == ""


class TestSortGap:
    def test_numeric(self):
        assert _sort_gap(1.5) == 1.5

    def test_string(self):
        assert _sort_gap("+1 LAP") == 9999.0

    def test_none(self):
        assert _sort_gap(None) == 9999.0


class TestBuildTemplateContext:
    def test_race_control_events(self):
        events = {
            "race_control": [
                {
                    "date": "2026-03-15T06:20:01+00:00",
                    "lap_number": 1,
                    "driver_number": None,
                    "message": "GREEN LIGHT - PIT EXIT OPEN",
                }
            ]
        }
        ctx = _build_template_context(
            events, DRIVER_MAP, None, datetime(2026, 3, 15, 6, 20), datetime(2026, 3, 15, 6, 21)
        )
        assert len(ctx["race_control"]) == 1
        assert ctx["race_control"][0]["message"] == "GREEN LIGHT - PIT EXIT OPEN"
        assert ctx["race_control"][0]["driver"] is None

    def test_race_control_with_driver(self):
        events = {
            "race_control": [
                {
                    "date": "2026-03-15T06:20:01+00:00",
                    "lap_number": 3,
                    "driver_number": 44,
                    "message": "TRACK LIMITS - TURN 4",
                }
            ]
        }
        ctx = _build_template_context(
            events, DRIVER_MAP, None, datetime(2026, 3, 15, 6, 20), datetime(2026, 3, 15, 6, 21)
        )
        assert ctx["race_control"][0]["driver"] == "Lewis HAMILTON (HAM)"

    def test_overtakes_both_drivers_resolved(self):
        events = {
            "overtakes": [
                {
                    "date": "2026-03-15T07:04:07+00:00",
                    "overtaking_driver_number": 44,
                    "overtaken_driver_number": 63,
                    "position": 2,
                }
            ]
        }
        ctx = _build_template_context(
            events, DRIVER_MAP, None, datetime(2026, 3, 15, 7, 4), datetime(2026, 3, 15, 7, 5)
        )
        assert ctx["overtakes"][0]["overtaking_driver"] == "Lewis HAMILTON (HAM)"
        assert ctx["overtakes"][0]["overtaken_driver"] == "George RUSSELL (RUS)"

    def test_pit_stops(self):
        events = {
            "pit": [
                {
                    "date": "2026-03-15T07:06:25+00:00",
                    "driver_number": 6,
                    "lap_number": 1,
                    "stop_duration": 2.7,
                    "pit_duration": 23.062,
                }
            ]
        }
        ctx = _build_template_context(
            events, DRIVER_MAP, None, datetime(2026, 3, 15, 7, 6), datetime(2026, 3, 15, 7, 7)
        )
        assert ctx["pit_stops"][0]["driver"] == "Nico HULKENBERG (HUL)"
        assert ctx["pit_stops"][0]["stop_duration"] == 2.7

    def test_position_snapshot_deduplication(self):
        events = {
            "position": [
                {"date": "2026-03-15T06:07:48+00:00", "driver_number": 12, "position": 1},
                {"date": "2026-03-15T06:07:48+00:00", "driver_number": 63, "position": 2},
                {"date": "2026-03-15T06:07:48+00:00", "driver_number": 44, "position": 3},
                # Later update — driver 44 moves to P2
                {"date": "2026-03-15T06:08:00+00:00", "driver_number": 44, "position": 2},
                {"date": "2026-03-15T06:08:00+00:00", "driver_number": 63, "position": 3},
            ]
        }
        ctx = _build_template_context(
            events, DRIVER_MAP, None, datetime(2026, 3, 15, 6, 7), datetime(2026, 3, 15, 6, 9)
        )
        standings = ctx["positions"]["standings"]
        # Should have 3 drivers (deduplicated), with latest positions
        assert len(standings) == 3
        assert standings[0]["position"] == 1
        assert standings[0]["driver"] == "Andrea Kimi ANTONELLI (ANT)"
        assert standings[1]["position"] == 2
        assert standings[1]["driver"] == "Lewis HAMILTON (HAM)"

    def test_intervals_with_lapped_car(self):
        events = {
            "intervals": [
                {"date": "2026-03-15T06:07:40+00:00", "driver_number": 12, "gap_to_leader": 0.0, "interval": 0.0},
                {"date": "2026-03-15T06:10:00+00:00", "driver_number": 55, "gap_to_leader": "+1 LAP", "interval": None},
            ]
        }
        ctx = _build_template_context(
            events, DRIVER_MAP, None, datetime(2026, 3, 15, 6, 7), datetime(2026, 3, 15, 6, 11)
        )
        gaps = ctx["intervals"]["gaps"]
        # Numeric gap sorts first, string gap sorts last
        assert gaps[0]["gap_to_leader"] == 0.0
        assert gaps[1]["gap_to_leader"] == "+1 LAP"

    def test_lap_times_excludes_null_durations(self):
        events = {
            "laps": [
                {"driver_number": 81, "lap_number": 1, "lap_duration": None},
                {"driver_number": 12, "lap_number": 1, "lap_duration": 100.643},
            ]
        }
        ctx = _build_template_context(
            events, DRIVER_MAP, None, datetime(2026, 3, 15, 7, 3), datetime(2026, 3, 15, 7, 5)
        )
        assert len(ctx["lap_times"]) == 1
        assert ctx["lap_times"][0]["duration"] == 100.643

    def test_weather_uses_latest(self):
        events = {
            "weather": [
                {
                    "date": "2026-03-15T06:08:35+00:00",
                    "air_temperature": 16.3,
                    "track_temperature": 26.5,
                    "humidity": 51.1,
                    "wind_speed": 2.1,
                    "wind_direction": 91,
                    "rainfall": 0,
                },
                {
                    "date": "2026-03-15T06:09:35+00:00",
                    "air_temperature": 16.3,
                    "track_temperature": 26.0,
                    "humidity": 51.1,
                    "wind_speed": 1.5,
                    "wind_direction": 111,
                    "rainfall": 0,
                },
            ]
        }
        ctx = _build_template_context(
            events, DRIVER_MAP, None, datetime(2026, 3, 15, 6, 8), datetime(2026, 3, 15, 6, 10)
        )
        # Should use the latest reading
        assert ctx["weather"]["track_temperature"] == 26.0
        assert ctx["weather"]["wind_speed"] == 1.5

    def test_stints(self):
        events = {
            "stints": [
                {
                    "driver_number": 6,
                    "stint_number": 1,
                    "compound": "SOFT",
                    "lap_start": 1,
                    "lap_end": 1,
                    "tyre_age_at_start": 3,
                }
            ]
        }
        ctx = _build_template_context(
            events, DRIVER_MAP, None, datetime(2026, 3, 15, 6, 0), datetime(2026, 3, 15, 6, 5)
        )
        assert ctx["stints"][0]["compound"] == "SOFT"
        assert ctx["stints"][0]["driver"] == "Nico HULKENBERG (HUL)"

    def test_previous_summary_included(self):
        ctx = _build_template_context(
            {"race_control": [{"date": "2026-03-15T06:20:01+00:00", "message": "test"}]},
            DRIVER_MAP,
            "Hamilton closed the gap...",
            datetime(2026, 3, 15, 6, 20),
            datetime(2026, 3, 15, 6, 21),
        )
        assert ctx["previous_summary"] == "Hamilton closed the gap..."

    def test_no_previous_summary(self):
        ctx = _build_template_context(
            {"race_control": [{"date": "2026-03-15T06:20:01+00:00", "message": "test"}]},
            DRIVER_MAP,
            None,
            datetime(2026, 3, 15, 6, 20),
            datetime(2026, 3, 15, 6, 21),
        )
        assert ctx["previous_summary"] is None

    def test_empty_events_not_in_context(self):
        ctx = _build_template_context(
            {"race_control": [{"date": "2026-03-15T06:20:01+00:00", "message": "test"}]},
            DRIVER_MAP,
            None,
            datetime(2026, 3, 15, 6, 20),
            datetime(2026, 3, 15, 6, 21),
        )
        assert "overtakes" not in ctx
        assert "pit_stops" not in ctx

    def test_no_positions_for_practice(self):
        """Practice sessions have no position/interval events — only laps."""
        events = {
            "laps": [
                {"driver_number": 44, "lap_number": 1, "lap_duration": 80.5},
                {"driver_number": 63, "lap_number": 1, "lap_duration": 81.2},
            ],
        }
        ctx = _build_template_context(
            events,
            DRIVER_MAP,
            None,
            datetime(2026, 3, 15, 6, 20),
            datetime(2026, 3, 15, 6, 21),
            session_type="Practice 1",
        )
        assert "positions" not in ctx
        assert "intervals" not in ctx
        assert "lap_times" in ctx
        assert len(ctx["lap_times"]) == 2


class TestFormatLapTime:
    def test_under_one_minute(self):
        assert _format_lap_time(58.456) == "0:58.456"

    def test_over_one_minute(self):
        assert _format_lap_time(88.456) == "1:28.456"

    def test_exact_minute(self):
        assert _format_lap_time(60.0) == "1:00.000"

    def test_none(self):
        assert _format_lap_time(None) == "N/A"

    def test_long_time(self):
        # Race total time: 5765.432s = 96:05.432
        assert _format_lap_time(5765.432) == "96:05.432"


class TestNonRaceStandings:
    def test_practice_standings_sorted_by_best_lap(self):
        events = {
            "laps": [
                {"driver_number": 44, "lap_number": 5, "lap_duration": 80.5},
                {"driver_number": 63, "lap_number": 3, "lap_duration": 79.8},
            ],
        }
        best_laps = {44: 80.5, 63: 79.8}
        ctx = _build_template_context(
            events,
            DRIVER_MAP,
            None,
            datetime(2026, 3, 15, 6, 20),
            datetime(2026, 3, 15, 6, 25),
            session_type="Practice 1",
            best_laps=best_laps,
        )
        assert "standings" in ctx
        assert "positions" not in ctx
        assert ctx["standings"][0]["driver"] == "George RUSSELL (RUS)"
        assert ctx["standings"][0]["best_lap"] == 79.8
        assert ctx["standings"][0]["gap"] == 0.0
        assert ctx["standings"][1]["driver"] == "Lewis HAMILTON (HAM)"
        assert ctx["standings"][1]["gap"] == pytest.approx(0.7)

    def test_qualifying_standings_include_q_times(self):
        events = {
            "laps": [
                {"driver_number": 44, "lap_number": 5, "lap_duration": 88.5},
            ],
        }
        best_laps = {44: 88.5, 63: 87.9}
        session_results = {
            44: {"duration": [90.1, 89.2, 88.5], "gap_to_leader": [0.5, 0.3, 0.6]},
            63: {"duration": [89.6, 88.9, 87.9], "gap_to_leader": [0.0, 0.0, 0.0]},
        }
        ctx = _build_template_context(
            events,
            DRIVER_MAP,
            None,
            datetime(2026, 3, 15, 6, 20),
            datetime(2026, 3, 15, 6, 25),
            session_type="Qualifying",
            best_laps=best_laps,
            session_results=session_results,
        )
        standings = ctx["standings"]
        assert standings[0]["driver"] == "George RUSSELL (RUS)"
        assert "q_times" in standings[0]
        assert "1:29.600" in standings[0]["q_times"]  # Q1
        assert "1:28.900" in standings[0]["q_times"]  # Q2
        assert "1:27.900" in standings[0]["q_times"]  # Q3

    def test_qualifying_eliminated_driver_q_times_show_na(self):
        events = {
            "laps": [
                {"driver_number": 44, "lap_number": 2, "lap_duration": 90.5},
            ],
        }
        best_laps = {44: 90.5}
        session_results = {
            44: {"duration": [90.5, 90.2, None], "gap_to_leader": [0.6, 1.2, None]},
        }
        ctx = _build_template_context(
            events,
            DRIVER_MAP,
            None,
            datetime(2026, 3, 15, 6, 20),
            datetime(2026, 3, 15, 6, 25),
            session_type="Qualifying",
            best_laps=best_laps,
            session_results=session_results,
        )
        assert "N/A" in ctx["standings"][0]["q_times"]

    def test_no_standings_without_best_laps(self):
        events = {
            "race_control": [{"date": "2026-03-15T06:20:01+00:00", "message": "test"}],
        }
        ctx = _build_template_context(
            events,
            DRIVER_MAP,
            None,
            datetime(2026, 3, 15, 6, 20),
            datetime(2026, 3, 15, 6, 25),
            session_type="Practice 1",
        )
        assert "standings" not in ctx


class TestBuildPrompt:
    @pytest.mark.asyncio
    async def test_returns_none_for_empty_window(self):
        db = AsyncMock()
        # No rows returned
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        result = await build_prompt(db, 12345, datetime(2026, 3, 15, 6, 0), datetime(2026, 3, 15, 6, 1), None)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_string_with_events(self):
        db = AsyncMock()

        # First call: fetch events
        event = MagicMock(spec=RaceEvent)
        event.source = "race_control"
        event.data = {"date": "2026-03-15T06:20:01+00:00", "message": "GREEN LIGHT", "lap_number": 1}

        events_result = MagicMock()
        events_result.scalars.return_value.all.return_value = [event]

        # Second call: fetch drivers
        driver = MagicMock(spec=Driver)
        driver.driver_number = 44
        driver.full_name = "Lewis HAMILTON"
        driver.name_acronym = "HAM"

        drivers_result = MagicMock()
        drivers_result.scalars.return_value.all.return_value = [driver]

        db.execute = AsyncMock(side_effect=[events_result, drivers_result])

        result = await build_prompt(db, 12345, datetime(2026, 3, 15, 6, 20), datetime(2026, 3, 15, 6, 21), None)
        assert result is not None
        assert "<race_window" in result
        assert "GREEN LIGHT" in result
        assert "<race_control>" in result
