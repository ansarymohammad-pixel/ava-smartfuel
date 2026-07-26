from datetime import UTC, datetime
import math

from app.schemas.prediction import PricePredictionResponse
from app.schemas.station import FuelType


class LstmPricePredictor:
    async def predict(
        self,
        *,
        fuel_type: FuelType,
        station_id: str | None,
        horizon_hours: int,
        current_price: float | None = None,
        average_price: float | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        sample_count: int = 0,
    ) -> PricePredictionResponse:
        if current_price and current_price > 0:
            average = average_price if average_price and average_price > 0 else current_price
            low = min_price if min_price and min_price > 0 else min(current_price, average)
            high = max_price if max_price and max_price > 0 else max(current_price, average)
            spread = max(high - low, 0.01)
            relative_position = min(max((current_price - low) / spread, 0.0), 1.0)

            # MVP decomposition: explainable until a real station history table is populated.
            trend = max(min((0.5 - relative_position) * 0.035, 0.06), -0.06)
            seasonal = math.sin((horizon_hours / 24.0) * math.tau) * 0.006
            residual = max(min((average - current_price) * 0.18, 0.025), -0.025)
            predicted = max(current_price + trend + seasonal + residual, 0.5)
            confidence = max(min(58 + min(sample_count, 12) * 3 + int(spread * 100), 88), 55)

            return PricePredictionResponse(
                fuel_type=fuel_type,
                station_id=station_id,
                predicted_price_eur_l=round(predicted, 3),
                horizon_hours=horizon_hours,
                model="STL-lite + AVA baseline",
                status="ok",
                message="Prediction indicative basee sur prix local, dispersion de zone et horizon.",
                trend_eur_l=round(trend, 3),
                seasonal_eur_l=round(seasonal, 3),
                residual_eur_l=round(residual, 3),
                confidence=confidence,
                history_points=max(sample_count, 0),
                basis="local_snapshot",
                generated_at=datetime.now(UTC),
            )

        return PricePredictionResponse(
            fuel_type=fuel_type,
            station_id=station_id,
            predicted_price_eur_l=None,
            horizon_hours=horizon_hours,
            model="LSTM-ready",
            status="needs_training",
            message="Collecter l'historique des prix avant entrainement LSTM.",
            confidence=0,
            basis="missing_price_history",
            generated_at=datetime.now(UTC),
        )

