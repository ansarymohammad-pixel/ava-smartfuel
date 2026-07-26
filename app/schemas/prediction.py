from datetime import datetime

from pydantic import BaseModel

from app.schemas.station import FuelType


class PricePredictionResponse(BaseModel):
    fuel_type: FuelType
    station_id: str | None = None
    predicted_price_eur_l: float | None = None
    horizon_hours: int
    model: str
    status: str
    message: str
    trend_eur_l: float = 0.0
    seasonal_eur_l: float = 0.0
    residual_eur_l: float = 0.0
    confidence: int = 50
    history_points: int = 0
    basis: str = "no_history"
    generated_at: datetime

