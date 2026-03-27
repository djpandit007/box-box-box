from dataclasses import dataclass
from enum import IntEnum


class Priority(IntEnum):
    P1 = 1  # every tick (10s)
    P2 = 2  # every 3rd tick (30s)
    P3 = 3  # every 6th tick (60s)


@dataclass(frozen=True)
class EndpointConfig:
    name: str
    path: str
    priority: Priority
    date_field: str = "date"  # field for incremental date>= filtering; "" = no incremental


ENDPOINTS: tuple[EndpointConfig, ...] = (
    # P1 — critical, every 10s
    EndpointConfig("race_control", "/race_control", Priority.P1),
    EndpointConfig("pit", "/pit", Priority.P1),
    EndpointConfig("overtakes", "/overtakes", Priority.P1),
    # P2 — important, every 30s
    EndpointConfig("position", "/position", Priority.P2),
    EndpointConfig("intervals", "/intervals", Priority.P2),
    # P3 — background, every 60s
    EndpointConfig("laps", "/laps", Priority.P3, date_field="date_start"),
    EndpointConfig("weather", "/weather", Priority.P3),
    EndpointConfig("stints", "/stints", Priority.P3, date_field=""),  # no date field; re-fetch entirely
    EndpointConfig("team_radio", "/team_radio", Priority.P3),
    EndpointConfig("session_result", "/session_result", Priority.P3, date_field=""),  # no date; re-fetch entirely
)
