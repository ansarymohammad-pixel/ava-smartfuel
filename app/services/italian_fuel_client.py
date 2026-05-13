import asyncio
import csv
import io
import time
from datetime import datetime
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.station import FuelType, StationPrice
from app.services.geo import haversine_km
from app.services.station_type import detect_station_type

ITALIAN_HEADERS = {
    "Accept": "text/csv,*/*",
    "User-Agent": "AVA-SmartFuel/1.0 (+https://ava-smartfuel)",
}

ITALIAN_FUEL_NAMES = {
    FuelType.gazole: ("gasolio", "diesel"),
    FuelType.sp95: ("benzina",),
    FuelType.e10: ("benzina",),
    FuelType.sp98: ("benzina speciale", "benzina 100", "superplus"),
    FuelType.e85: ("e85", "bioetanolo"),
    FuelType.gpl: ("gpl",),
}

_ITALIAN_DATA_CACHE: tuple[float, list[StationPrice]] | None = None
_ITALIAN_DATA_LOCK = asyncio.Lock()


class ItalianFuelClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch_nearby(
        self,
        *,
        lat: float,
        lon: float,
        fuel_type: FuelType,
        radius_km: float,
        limit: int,
    ) -> list[StationPrice]:
        all_prices = await self._fetch_italian_prices()
        accepted_fuels = {fuel_type}
        if fuel_type == FuelType.e10:
            accepted_fuels.add(FuelType.sp95)
        stations = [
            station
            for station in all_prices
            if station.fuel_type in accepted_fuels
            and haversine_km(lat, lon, station.lat, station.lon) <= radius_km
        ]
        stations.sort(key=lambda station: (station.price_eur_l, haversine_km(lat, lon, station.lat, station.lon)))
        return stations[:limit]

    async def _fetch_italian_prices(self) -> list[StationPrice]:
        global _ITALIAN_DATA_CACHE

        now = time.monotonic()
        if _ITALIAN_DATA_CACHE and now - _ITALIAN_DATA_CACHE[0] < settings.official_cache_ttl_seconds:
            return _ITALIAN_DATA_CACHE[1]

        async with _ITALIAN_DATA_LOCK:
            now = time.monotonic()
            if _ITALIAN_DATA_CACHE and now - _ITALIAN_DATA_CACHE[0] < settings.official_cache_ttl_seconds:
                return _ITALIAN_DATA_CACHE[1]

            stations_csv, prices_csv = await asyncio.gather(
                self._download_csv(settings.italian_stations_csv_url),
                self._download_csv(settings.italian_prices_csv_url),
            )
            stations = self._parse_stations(stations_csv)
            prices = self._parse_prices(prices_csv, stations)
            _ITALIAN_DATA_CACHE = (time.monotonic(), prices)
            return prices

    async def _download_csv(self, url: str) -> str:
        response = await self._client.get(
            url,
            headers=ITALIAN_HEADERS,
            follow_redirects=True,
            timeout=httpx.Timeout(45.0, connect=20.0),
        )
        response.raise_for_status()
        response.encoding = response.encoding or "latin-1"
        return response.text

    def _parse_stations(self, raw_csv: str) -> dict[str, dict[str, Any]]:
        rows = self._dict_rows(raw_csv)
        stations: dict[str, dict[str, Any]] = {}
        for row in rows:
            station_id = self._value(row, "idImpianto", "idimpianto", "id")
            lat = self._italian_float(self._value(row, "latitudine", "Latitudine"))
            lon = self._italian_float(self._value(row, "longitudine", "Longitudine"))
            if not station_id or lat is None or lon is None:
                continue
            stations[str(station_id)] = {
                "station_id": str(station_id),
                "brand": self._value(row, "Bandiera", "bandiera", "Gestore", "gestore"),
                "name": self._value(row, "Nome Impianto", "nomeImpianto", "Gestore", "gestore"),
                "address": self._value(row, "Indirizzo", "indirizzo"),
                "city": self._value(row, "Comune", "comune"),
                "postal_code": self._value(row, "Cap", "CAP", "cap"),
                "station_type": detect_station_type(
                    self._value(row, "Bandiera", "bandiera", "Gestore", "gestore"),
                    self._value(row, "Nome Impianto", "nomeImpianto"),
                    self._value(row, "Indirizzo", "indirizzo"),
                    self._value(row, "Comune", "comune"),
                    self._value(row, "Tipo Impianto", "tipoImpianto"),
                ),
                "lat": lat,
                "lon": lon,
            }
        return stations

    def _parse_prices(
        self,
        raw_csv: str,
        stations: dict[str, dict[str, Any]],
    ) -> list[StationPrice]:
        result: list[StationPrice] = []
        for row in self._dict_rows(raw_csv):
            station_id = str(self._value(row, "idImpianto", "idimpianto", "id") or "")
            station = stations.get(station_id)
            if not station:
                continue
            fuel_type = self._fuel_type(self._value(row, "descCarburante", "carburante", "nomeCarburante"))
            price = self._italian_float(self._value(row, "prezzo", "Prezzo"))
            if fuel_type is None or price is None:
                continue
            result.append(
                StationPrice(
                    station_id=station["station_id"],
                    name=station.get("name") or station.get("brand"),
                    brand=station.get("brand") or station.get("name"),
                    address=station.get("address"),
                    city=station.get("city"),
                    postal_code=str(station.get("postal_code") or ""),
                    lat=station["lat"],
                    lon=station["lon"],
                    fuel_type=fuel_type,
                    price_eur_l=price,
                    station_type=station.get("station_type"),
                    updated_at=self._datetime(self._value(row, "dtComu", "dataComunicazione", "Data")),
                    services=[],
                )
            )
        return result

    def _dict_rows(self, raw_csv: str) -> list[dict[str, str]]:
        lines = [line for line in raw_csv.splitlines() if line.strip()]
        if lines and not any(separator in lines[0] for separator in (";", "|")):
            lines = lines[1:]
        header = lines[0] if lines else ""
        delimiter = "|" if "|" in header else ";"
        reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delimiter)
        return [dict(row) for row in reader]

    def _fuel_type(self, value: Any) -> FuelType | None:
        normalized = str(value or "").strip().lower()
        for fuel_type, names in ITALIAN_FUEL_NAMES.items():
            if any(name in normalized for name in names):
                return fuel_type
        return None

    def _value(self, row: dict[str, Any], *keys: str) -> Any:
        normalized = {key.strip().lower(): value for key, value in row.items() if key}
        for key in keys:
            value = normalized.get(key.strip().lower())
            if value not in (None, ""):
                return value
        return None

    def _italian_float(self, value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value).strip().replace(",", "."))
        except ValueError:
            return None

    def _datetime(self, value: Any) -> datetime | None:
        if not value:
            return None
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(str(value), fmt)
            except ValueError:
                pass
        return None
