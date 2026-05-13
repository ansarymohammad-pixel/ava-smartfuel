import re
import unicodedata
from typing import Any

from app.schemas.station import StationType


MOTORWAY_WORDS = (
    "autoroute",
    "autopista",
    "autovia",
    "autostrada",
    "aire de service",
    "area de servicio",
    "area servicio",
    "area di servizio",
    "station autoroute",
)

ROAD_WORDS = (
    "route nationale",
    "rn ",
    "rd ",
    "nationale",
    "carretera",
    "strada statale",
    "ss ",
)

MOTORWAY_CODE_RE = re.compile(r"\b(?:a|ap|e)\s*-?\s*\d{1,3}\b")


def detect_station_type(*values: Any) -> StationType:
    text = _normalize(" ".join(str(value) for value in values if value))
    if any(word in text for word in MOTORWAY_WORDS) or MOTORWAY_CODE_RE.search(text):
        return StationType.motorway
    if any(word in text for word in ROAD_WORDS):
        return StationType.road
    return StationType.city


def station_type_price_penalty(station_type: StationType) -> float:
    if station_type == StationType.motorway:
        return 0.045
    if station_type == StationType.road:
        return 0.015
    return 0.0


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))
