from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class FuelType(str, Enum):
    gazole = "Gazole"
    sp95 = "SP95"
    e10 = "E10"
    sp98 = "SP98"
    e85 = "E85"
    gpl = "GPL"


class StationPrice(BaseModel):
    station_id: str
    name: str | None = None
    brand: str | None = None
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None
    lat: float
    lon: float
    fuel_type: FuelType
    price_eur_l: float = Field(gt=0)
    updated_at: datetime | None = None
    services: list[str] = []


class AvaScore(BaseModel):
    label: str
    score: int = Field(ge=0, le=100)
    full_tank_cost_eur: float
    detour_cost_eur: float
    estimated_savings_eur: float
    net_gain_eur: float
    detour_km: float
    reason: str


class StationChoice(BaseModel):
    station: StationPrice
    distance_km: float
    google_maps_url: str
    ava: AvaScore
    best_choice: bool = False


class NearbyStationsResponse(BaseModel):
    fuel_type: FuelType
    user_lat: float
    user_lon: float
    liters: float
    consumption_l_100km: float
    radius_km: float
    average_price_eur_l: float | None
    choices: list[StationChoice]

