import pytest

from boxboxbox.ingestion.schemas import ENDPOINT_MODELS


FIXTURE_NAMES = [name for name in ENDPOINT_MODELS if name != "team_radio"]


class TestFixtureValidation:
    @pytest.mark.parametrize("endpoint_name", FIXTURE_NAMES)
    def test_fixture_validates_against_schema(self, load_fixture, endpoint_name):
        data = load_fixture(endpoint_name)
        model_cls = ENDPOINT_MODELS[endpoint_name]
        for item in data:
            model_cls.model_validate(item)

    @pytest.mark.parametrize("endpoint_name", FIXTURE_NAMES)
    def test_extra_fields_preserved(self, load_fixture, endpoint_name):
        data = load_fixture(endpoint_name)
        if not data:
            pytest.skip(f"No fixture data for {endpoint_name}")
        model_cls = ENDPOINT_MODELS[endpoint_name]
        item = data[0].copy()
        item["_unknown_field"] = "test_value"
        validated = model_cls.model_validate(item)
        dumped = validated.model_dump()
        assert dumped["_unknown_field"] == "test_value"


class TestIntervalEdgeCases:
    def test_string_gap_to_leader(self):
        from boxboxbox.ingestion.schemas import IntervalResponse

        data = {
            "date": "2026-03-15T06:10:00",
            "session_key": 11245,
            "gap_to_leader": "+1 LAP",
            "interval": None,
            "meeting_key": 1280,
            "driver_number": 55,
        }
        result = IntervalResponse.model_validate(data)
        assert result.gap_to_leader == "+1 LAP"
        assert result.interval is None
