from enum import Enum


class CountryCode(str, Enum):
    france = "FR"
    spain = "ES"
    italy = "IT"


def detect_country(lat: float, lon: float) -> CountryCode:
    if 27.0 <= lat <= 44.5 and -19.0 <= lon <= 5.0:
        return CountryCode.spain
    if 35.0 <= lat <= 47.8 and 6.0 <= lon <= 19.5:
        return CountryCode.italy
    return CountryCode.france


def normalize_country(value: str | None, lat: float, lon: float) -> CountryCode:
    if not value:
        return detect_country(lat, lon)
    normalized = value.strip().upper()
    if normalized in {"ES", "ESP", "SPAIN", "ESPAGNE"}:
        return CountryCode.spain
    if normalized in {"IT", "ITA", "ITALY", "ITALIE", "ITALIA"}:
        return CountryCode.italy
    return CountryCode.france
