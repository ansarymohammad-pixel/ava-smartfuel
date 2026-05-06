from datetime import UTC, datetime

from app.schemas.prediction import PricePredictionResponse
from app.schemas.station import FuelType


class LstmPricePredictor:
    async def predict(
        self,
        *,
        fuel_type: FuelType,
        station_id: str | None,
        horizon_hours: int,
    ) -> PricePredictionResponse:
        return PricePredictionResponse(
            fuel_type=fuel_type,
            station_id=station_id,
            predicted_price_eur_l=None,
            horizon_hours=horizon_hours,
            model="LSTM",
            status="needs_training",
            message="Collecter l'historique des prix avant entrainement LSTM.",
            generated_at=datetime.now(UTC),
        )

