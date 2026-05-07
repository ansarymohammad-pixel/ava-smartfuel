from datetime import datetime
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.station import FuelType, StationPrice
from app.services.geo import haversine_km

SPANISH_PRICE_FIELDS = {
    FuelType.gazole: ("Precio Gasoleo A", "Precio Gasóleo A"),
    FuelType.sp95: ("Precio Gasolina 95 E5", "Precio Gasolina 95 E10"),
    FuelType.e10: ("Precio Gasolina 95 E10", "Precio Gasolina 95 E5"),
    FuelType.sp98: ("Precio Gasolina 98 E5", "Precio Gasolina 98 E10"),
    FuelType.e85: ("Precio Bioetanol",),
    FuelType.gpl: ("Precio Gases licuados del petróleo", "Precio GLP"),
}


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
        response = await self._client.get(settings.spanish_fuel_api_url)
        response.raise_for_status()
        rows = response.json().get("ListaEESSPrecio", [])
        stations = [station for row in rows if (station := self._parse(row, fuel_type))]
        stations = [
            station
            for station in stations
            if haversine_km(lat, lon, station.lat, station.lon) <= radius_km
        ]
        stations.sort(key=lambda station: haversine_km(lat, lon, station.lat, station.lon))
        return stations[:limit]

    def _parse(self, row: dict[str, Any], fuel_type: FuelType) -> StationPrice | None:
        price = self._first_float(row, SPANISH_PRICE_FIELDS[fuel_type])
        lat = self._spanish_float(row.get("Latitud"))
        lon = self._spanish_float(row.get("Longitud (WGS84)") or row.get("Longitud"))
        if price is None or lat is None or lon is None:
            return None
        return StationPrice(
            station_id=str(row.get("IDEESS") or row.get("IDEstacion") or ""),
            name=row.get("Rótulo") or row.get("Rotulo"),
            brand=row.get("Rótulo") or row.get("Rotulo"),
            address=row.get("Dirección") or row.get("Direccion"),
            city=row.get("Localidad") or row.get("Municipio"),
            postal_code=str(row.get("C.P.") or row.get("CP") or ""),
            lat=lat,
            lon=lon,
            fuel_type=fuel_type,
            price_eur_l=price,
            updated_at=self._datetime(row.get("Fecha") or row.get("Fecha Actualización")),
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
