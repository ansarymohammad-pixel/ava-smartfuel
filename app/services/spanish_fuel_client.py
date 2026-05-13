import asyncio
import time
from datetime import datetime
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.station import FuelType, StationPrice
from app.services.geo import haversine_km
from app.services.station_type import detect_station_type

SPANISH_HEADERS = {
    "Accept": "application/json,text/plain,*/*",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36 AVA-SmartFuel/1.0"
    ),
}

SPANISH_PRICE_FIELDS = {
    FuelType.gazole: ("Precio Gasoleo A", "Precio Gasóleo A", "Precio GasÃ³leo A"),
    FuelType.sp95: ("Precio Gasolina 95 E5", "Precio Gasolina 95 E10"),
    FuelType.e10: ("Precio Gasolina 95 E10", "Precio Gasolina 95 E5"),
    FuelType.sp98: ("Precio Gasolina 98 E5", "Precio Gasolina 98 E10"),
    FuelType.e85: ("Precio Bioetanol",),
    FuelType.gpl: ("Precio Gases licuados del petróleo", "Precio Gases licuados del petrÃ³leo", "Precio GLP"),
}

_SPANISH_DATA_CACHE: tuple[float, dict[str, Any]] | None = None
_SPANISH_DATA_LOCK = asyncio.Lock()


class SpanishFuelClient:
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
        data = await self._fetch_spanish_prices()
        rows = data.get("ListaEESSPrecio", [])
        stations = [station for row in rows if (station := self._parse(row, fuel_type))]
        stations = [
            station
            for station in stations
            if haversine_km(lat, lon, station.lat, station.lon) <= radius_km
        ]
        stations.sort(key=lambda station: haversine_km(lat, lon, station.lat, station.lon))
        return stations[:limit]

    async def _fetch_spanish_prices(self) -> dict[str, Any]:
        global _SPANISH_DATA_CACHE

        now = time.monotonic()
        if _SPANISH_DATA_CACHE and now - _SPANISH_DATA_CACHE[0] < settings.official_cache_ttl_seconds:
            return _SPANISH_DATA_CACHE[1]

        async with _SPANISH_DATA_LOCK:
            now = time.monotonic()
            if _SPANISH_DATA_CACHE and now - _SPANISH_DATA_CACHE[0] < settings.official_cache_ttl_seconds:
                return _SPANISH_DATA_CACHE[1]

            data = await self._download_spanish_prices()
            _SPANISH_DATA_CACHE = (time.monotonic(), data)
            return data

    async def _download_spanish_prices(self) -> dict[str, Any]:
        last_error: Exception | None = None
        for _ in range(3):
            try:
                response = await self._client.get(
                    settings.spanish_fuel_api_url,
                    headers=SPANISH_HEADERS,
                    follow_redirects=True,
                    timeout=httpx.Timeout(35.0, connect=20.0),
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as exc:
                last_error = exc

        # Railway can fail TLS/network negotiation with this government host.
        # A short-lived client with relaxed cert verification is used only as
        # fallback for the official Spanish open-data endpoint.
        async with httpx.AsyncClient(
            headers=SPANISH_HEADERS,
            follow_redirects=True,
            timeout=httpx.Timeout(45.0, connect=25.0),
            verify=False,
        ) as fallback_client:
            try:
                response = await fallback_client.get(settings.spanish_fuel_api_url)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Spanish official fuel API unavailable: {exc}") from (last_error or exc)

    def _parse(self, row: dict[str, Any], fuel_type: FuelType) -> StationPrice | None:
        price = self._first_float(row, SPANISH_PRICE_FIELDS[fuel_type])
        lat = self._spanish_float(row.get("Latitud"))
        lon = self._spanish_float(row.get("Longitud (WGS84)") or row.get("Longitud"))
        if price is None or lat is None or lon is None:
            return None
        return StationPrice(
            station_id=str(row.get("IDEESS") or row.get("IDEstacion") or ""),
            name=row.get("Rótulo") or row.get("RÃ³tulo") or row.get("Rotulo"),
            brand=row.get("Rótulo") or row.get("RÃ³tulo") or row.get("Rotulo"),
            address=row.get("Dirección") or row.get("DirecciÃ³n") or row.get("Direccion"),
            city=row.get("Localidad") or row.get("Municipio"),
            postal_code=str(row.get("C.P.") or row.get("CP") or ""),
            lat=lat,
            lon=lon,
            fuel_type=fuel_type,
            price_eur_l=price,
            station_type=detect_station_type(
                row.get("Rotulo"),
                row.get("Rótulo"),
                row.get("Dirección"),
                row.get("Direccion"),
                row.get("Localidad"),
                row.get("Municipio"),
                row.get("Margen"),
                row.get("Tipo Venta"),
            ),
            updated_at=self._datetime(row.get("Fecha") or row.get("Fecha Actualización") or row.get("Fecha ActualizaciÃ³n")),
            services=[row.get("Horario") or ""],
        )

    def _first_float(self, row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return self._spanish_float(value)
        return None

    def _spanish_float(self, value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace(",", "."))
        except ValueError:
            return None

    def _datetime(self, value: Any) -> datetime | None:
        if not value:
            return None
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
            try:
                return datetime.strptime(str(value), fmt)
            except ValueError:
                pass
        return None
