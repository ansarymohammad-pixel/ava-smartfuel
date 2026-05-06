from datetime import datetime
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.station import FuelType, StationPrice

PRICE_FIELDS = {
    FuelType.gazole: ("gazole_prix",),
    FuelType.sp95: ("sp95_prix",),
    FuelType.e10: ("e10_prix",),
    FuelType.sp98: ("sp98_prix",),
    FuelType.e85: ("e85_prix",),
    FuelType.gpl: ("gplc_prix", "gpl_prix"),
}


class OfficialFuelClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=20)

    async def __aenter__(self) -> "OfficialFuelClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def fetch_nearby(
        self,
        *,
        lat: float,
        lon: float,
        fuel_type: FuelType,
        radius_km: float,
        limit: int,
    ) -> list[StationPrice]:
        point = f"geom'POINT({lon} {lat})'"
        where = f"within_distance(geom, {point}, {radius_km}km)"
        params = {"limit": limit, "where": where, "order_by": f"distance(geom, {point})"}
        response = await self._client.get(settings.official_fuel_api_url, params=params)
        response.raise_for_status()
        rows = response.json().get("results", [])
        return [station for row in rows if (station := self._parse(row, fuel_type))]

    def _parse(self, row: dict[str, Any], fuel_type: FuelType) -> StationPrice | None:
        price = self._first_float(row, PRICE_FIELDS[fuel_type])
        coords = self._coords(row)
        if price is None or coords is None:
            return None
        lat, lon = coords
        return StationPrice(
            station_id=str(row.get("id") or row.get("id_pdv") or ""),
            name=row.get("nom"),
            brand=row.get("enseigne") or row.get("marque"),
            address=row.get("adresse"),
            city=row.get("ville") or row.get("commune"),
            postal_code=str(row.get("cp") or row.get("code_postal") or ""),
            lat=lat,
            lon=lon,
            fuel_type=fuel_type,
            price_eur_l=price,
            updated_at=self._datetime(row.get(f"{fuel_type.value.lower()}_maj")),
            services=[],
        )

    def _coords(self, row: dict[str, Any]) -> tuple[float, float] | None:
        value = row.get("geom") or row.get("geo_point") or row.get("geo_point_2d")
        if isinstance(value, dict):
            if "lat" in value and "lon" in value:
                return float(value["lat"]), float(value["lon"])
            if "coordinates" in value:
                lon, lat = value["coordinates"][:2]
                return float(lat), float(lon)
        return None

    def _first_float(self, row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return float(value)
        return None

    def _datetime(self, value: Any) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

