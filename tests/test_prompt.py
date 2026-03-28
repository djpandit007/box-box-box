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
        assert _driver_name(DRIVER_MAP, 44) == "Lewis HAMILTON (HAM, Ferrari)"

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
        assert ctx["race_control"][0]["driver"] == "Lewis HAMILTON (HAM, Ferrari)"

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
        assert ctx["overtakes"][0]["overtaking_driver"] == "Lewis HAMILTON (HAM, Ferrari)"
        assert ctx["overtakes"][0]["overtaken_driver"] == "George RUSSELL (RUS, Mercedes)"

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
        assert ctx["pit_stops"][0]["driver"] == "Nico HULKENBERG (HUL, Sauber)"
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
        assert standings[0]["driver"] == "Andrea Kimi ANTONELLI (ANT, Mercedes)"
        assert standings[1]["position"] == 2
        assert standings[1]["driver"] == "Lewis HAMILTON (HAM, Ferrari)"

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
        assert ctx["stints"][0]["driver"] == "Nico HULKENBERG (HUL, Sauber)"

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
        assert ctx["standings"][0]["driver"] == "George RUSSELL (RUS, Mercedes)"
        assert ctx["standings"][0]["best_lap"] == 79.8
        assert ctx["standings"][0]["gap"] == 0.0
        assert ctx["standings"][1]["driver"] == "Lewis HAMILTON (HAM, Ferrari)"
        assert ctx["standings"][1]["gap"] == pytest.approx(0.7)

    def test_qualifying_standings_no_q_times(self):
        """q_times should not leak into standings — only shown when phase ends."""
        events = {
            "laps": [{"driver_number": 44, "lap_number": 5, "lap_duration": 88.5}],
        }
        best_laps = {44: 88.5, 63: 87.9}
        session_results = {
            44: {"duration": [90.1, 89.2, 88.5]},
            63: {"duration": [89.6, 88.9, 87.9]},
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
        for s in ctx["standings"]:
            assert "q_times" not in s

    def test_qualifying_phase_passed_to_context(self):
        events = {
            "laps": [{"driver_number": 44, "lap_number": 1, "lap_duration": 90.0}],
        }
        ctx = _build_template_context(
            events,
            DRIVER_MAP,
            None,
            datetime(2026, 3, 15, 6, 20),
            datetime(2026, 3, 15, 6, 25),
            session_type="Qualifying",
            best_laps={44: 90.0},
            qualifying_phase=2,
        )
        assert ctx["qualifying_phase"] == "Q2"

    def test_no_significant_data_flag(self):
        events = {
            "weather": [
                {
                    "date": "2026-03-15T06:20:00+00:00",
                    "air_temperature": 30.0,
                    "track_temperature": 45.0,
                    "humidity": 40.0,
                    "wind_speed": 3.0,
                    "wind_direction": 180,
                    "rainfall": 0,
                },
            ],
        }
        ctx = _build_template_context(
            events,
            DRIVER_MAP,
            None,
            datetime(2026, 3, 15, 6, 20),
            datetime(2026, 3, 15, 6, 25),
            session_type="Qualifying",
        )
        assert ctx["no_significant_data"] is True

    def test_no_significant_data_not_set_with_laps(self):
        events = {
            "laps": [{"driver_number": 44, "lap_number": 1, "lap_duration": 90.0}],
        }
        ctx = _build_template_context(
            events,
            DRIVER_MAP,
            None,
            datetime(2026, 3, 15, 6, 20),
            datetime(2026, 3, 15, 6, 25),
            session_type="Qualifying",
            best_laps={44: 90.0},
        )
        assert "no_significant_data" not in ctx

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


class TestQualifyingPhaseResults:
    def _session_results(self):
        return {
            6: {"position": 16, "duration": [91.5, None, None]},
            63: {"position": 11, "duration": [89.8, 90.1, None]},
            44: {"position": 1, "duration": [89.5, 88.9, 87.8]},
            16: {"position": 2, "duration": [89.6, 89.0, 87.9]},
        }

    def test_q1_end_shows_only_q1_eliminated(self):
        events = {
            "race_control": [
                {"date": "2026-03-15T06:18:00+00:00", "qualifying_phase": 1, "message": "SESSION FINISHED"},
            ],
            "laps": [{"driver_number": 44, "lap_number": 1, "lap_duration": 89.5}],
        }
        ctx = _build_template_context(
            events,
            DRIVER_MAP,
            None,
            datetime(2026, 3, 15, 6, 15),
            datetime(2026, 3, 15, 6, 20),
            session_type="Qualifying",
            best_laps={44: 87.8, 63: 89.8, 6: 91.5, 16: 87.9},
            session_results=self._session_results(),
        )
        elim = ctx["qualifying_eliminations"]
        assert "q1" in elim
        assert "q2" not in elim
        assert len(elim["q1"]) == 1
        assert elim["q1"][0]["driver"] == "Nico HULKENBERG (HUL, Sauber)"
        assert elim["q1"][0]["q1_time"] == 91.5

    def test_q2_end_shows_only_q2_eliminated(self):
        events = {
            "race_control": [
                {"date": "2026-03-15T06:33:00+00:00", "qualifying_phase": 2, "message": "SESSION FINISHED"},
            ],
            "laps": [{"driver_number": 44, "lap_number": 5, "lap_duration": 88.9}],
        }
        ctx = _build_template_context(
            events,
            DRIVER_MAP,
            None,
            datetime(2026, 3, 15, 6, 30),
            datetime(2026, 3, 15, 6, 35),
            session_type="Qualifying",
            best_laps={44: 87.8, 63: 89.8, 6: 91.5, 16: 87.9},
            session_results=self._session_results(),
        )
        elim = ctx["qualifying_eliminations"]
        assert "q2" in elim
        assert "q1" not in elim
        assert len(elim["q2"]) == 1
        assert elim["q2"][0]["driver"] == "George RUSSELL (RUS, Mercedes)"

    def test_q3_end_shows_top10(self):
        events = {
            "race_control": [
                {"date": "2026-03-15T06:48:00+00:00", "qualifying_phase": 3, "message": "SESSION FINISHED"},
            ],
            "laps": [{"driver_number": 44, "lap_number": 8, "lap_duration": 87.8}],
        }
        ctx = _build_template_context(
            events,
            DRIVER_MAP,
            None,
            datetime(2026, 3, 15, 6, 45),
            datetime(2026, 3, 15, 6, 50),
            session_type="Qualifying",
            best_laps={44: 87.8, 63: 89.8, 6: 91.5, 16: 87.9},
            session_results=self._session_results(),
        )
        assert "qualifying_eliminations" not in ctx
        assert "qualifying_top10" in ctx
        top10 = ctx["qualifying_top10"]
        assert top10[0]["position"] == 1
        assert top10[0]["driver"] == "Lewis HAMILTON (HAM, Ferrari)"
        assert top10[0]["q3_time"] == 87.8
        assert top10[1]["position"] == 2

    def test_q1_order_preserved_by_position(self):
        events = {
            "race_control": [
                {"date": "2026-03-15T06:18:00+00:00", "qualifying_phase": 1, "message": "SESSION FINISHED"},
            ],
            "laps": [{"driver_number": 44, "lap_number": 1, "lap_duration": 90.0}],
        }
        session_results = {
            63: {"position": 17, "duration": [92.0, None, None]},
            6: {"position": 16, "duration": [91.5, None, None]},
        }
        ctx = _build_template_context(
            events,
            DRIVER_MAP,
            None,
            datetime(2026, 3, 15, 6, 15),
            datetime(2026, 3, 15, 6, 20),
            session_type="Qualifying",
            best_laps={44: 88.0, 63: 92.0, 6: 91.5},
            session_results=session_results,
        )
        q1 = ctx["qualifying_eliminations"]["q1"]
        assert q1[0]["driver"] == "Nico HULKENBERG (HUL, Sauber)"  # P16
        assert q1[1]["driver"] == "George RUSSELL (RUS, Mercedes)"  # P17

    def test_no_eliminations_without_session_finished(self):
        events = {
            "race_control": [
                {"date": "2026-03-15T06:15:00+00:00", "qualifying_phase": None, "message": "GREEN LIGHT"},
            ],
            "laps": [{"driver_number": 44, "lap_number": 1, "lap_duration": 90.0}],
        }
        ctx = _build_template_context(
            events,
            DRIVER_MAP,
            None,
            datetime(2026, 3, 15, 6, 15),
            datetime(2026, 3, 15, 6, 20),
            session_type="Qualifying",
            best_laps={44: 90.0},
            session_results=self._session_results(),
        )
        assert "qualifying_eliminations" not in ctx
        assert "qualifying_top10" not in ctx

    def test_no_eliminations_for_practice(self):
        events = {
            "laps": [{"driver_number": 44, "lap_number": 1, "lap_duration": 90.0}],
        }
        ctx = _build_template_context(
            events,
            DRIVER_MAP,
            None,
            datetime(2026, 3, 15, 6, 20),
            datetime(2026, 3, 15, 6, 25),
            session_type="Practice 1",
            best_laps={44: 90.0},
        )
        assert "qualifying_eliminations" not in ctx
        assert "qualifying_top10" not in ctx


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
