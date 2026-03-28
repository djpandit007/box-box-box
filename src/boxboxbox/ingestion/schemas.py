from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, field_validator


class SessionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_key: int
    session_type: str
    session_name: str
    date_start: datetime
    date_end: datetime
    meeting_key: int
    circuit_key: int
    circuit_short_name: str
    country_key: int
    country_code: str
    country_name: str
    location: str
    gmt_offset: str
    year: int

    @field_validator("date_start", "date_end")
    @classmethod
    def _normalize_dt(cls, v: datetime) -> datetime:
        # DB column types are TIMESTAMP WITHOUT TIME ZONE; normalize to UTC-naive.
        if v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v


class DriverResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    meeting_key: int
    session_key: int
    driver_number: int
    broadcast_name: str
    full_name: str
    name_acronym: str
    team_name: str
    team_colour: str
    first_name: str
    last_name: str
    headshot_url: str
    country_code: str | None = None


class RaceControlResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    meeting_key: int
    session_key: int
    date: datetime
    driver_number: int | None = None
    lap_number: int | None = None
    category: str
    flag: str | None = None
    scope: str | None = None
    sector: int | None = None
    qualifying_phase: int | None = None
    message: str

    @field_validator("date")
    @classmethod
    def _normalize_dt(cls, v: datetime) -> datetime:
        if v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v


class PositionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    date: datetime
    session_key: int
    position: int
    meeting_key: int
    driver_number: int

    @field_validator("date")
    @classmethod
    def _normalize_dt(cls, v: datetime) -> datetime:
        if v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v


class IntervalResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    date: datetime
    session_key: int
    gap_to_leader: float | str | None = None
    interval: float | str | None = None
    meeting_key: int
    driver_number: int

    @field_validator("date")
    @classmethod
    def _normalize_dt(cls, v: datetime) -> datetime:
        if v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v


class LapResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    meeting_key: int
    session_key: int
    driver_number: int
    lap_number: int
    date_start: datetime | None = None
    duration_sector_1: float | None = None
    duration_sector_2: float | None = None
    duration_sector_3: float | None = None
    i1_speed: int | None = None
    i2_speed: int | None = None
    is_pit_out_lap: bool
    lap_duration: float | None = None
    segments_sector_1: list[int | None] | None = None
    segments_sector_2: list[int | None] | None = None
    segments_sector_3: list[int | None] | None = None
    st_speed: int | None = None

    @field_validator("date_start")
    @classmethod
    def _normalize_dt(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        if v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v


class OvertakeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    meeting_key: int
    session_key: int
    overtaking_driver_number: int
    overtaken_driver_number: int
    date: datetime
    position: int

    @field_validator("date")
    @classmethod
    def _normalize_dt(cls, v: datetime) -> datetime:
        if v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v


class PitResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    date: datetime
    session_key: int
    lap_number: int
    driver_number: int
    stop_duration: float | None = None
    lane_duration: float | None = None
    pit_duration: float | None = None
    meeting_key: int

    @field_validator("date")
    @classmethod
    def _normalize_dt(cls, v: datetime) -> datetime:
        if v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v


class StintResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    meeting_key: int
    session_key: int
    stint_number: int
    driver_number: int
    lap_start: int
    lap_end: int
    compound: str
    tyre_age_at_start: int


class WeatherResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    date: datetime
    session_key: int
    air_temperature: float
    humidity: float
    rainfall: int
    meeting_key: int
    pressure: float
    wind_direction: int
    wind_speed: float
    track_temperature: float

    @field_validator("date")
    @classmethod
    def _normalize_dt(cls, v: datetime) -> datetime:
        if v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v


class TeamRadioResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    driver_number: int
    date: datetime
    recording_url: str
    session_key: int
    meeting_key: int

    @field_validator("date")
    @classmethod
    def _normalize_dt(cls, v: datetime) -> datetime:
        if v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v


class SessionResultResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_key: int
    meeting_key: int
    driver_number: int
    position: int | None = None
    number_of_laps: int | None = None
    points: int | None = None
    dnf: bool = False
    dns: bool = False
    dsq: bool = False
    duration: float | list[float] | None = None
    gap_to_leader: float | str | list[float] | None = None


class StartingGridResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    meeting_key: int
    session_key: int
    driver_number: int
    position: int
    date: datetime

    @field_validator("date")
    @classmethod
    def _normalize_dt(cls, v: datetime) -> datetime:
        if v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v


ENDPOINT_MODELS: dict[str, type[BaseModel]] = {
    "sessions": SessionResponse,
    "drivers": DriverResponse,
    "race_control": RaceControlResponse,
    "position": PositionResponse,
    "intervals": IntervalResponse,
    "laps": LapResponse,
    "overtakes": OvertakeResponse,
    "pit": PitResponse,
    "stints": StintResponse,
    "weather": WeatherResponse,
    "team_radio": TeamRadioResponse,
    "session_result": SessionResultResponse,
    "starting_grid": StartingGridResponse,
}
