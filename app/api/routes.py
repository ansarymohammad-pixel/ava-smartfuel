from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.schemas.prediction import PricePredictionResponse
from app.schemas.station import FuelType, NearbyStationsResponse
from app.services.country import normalize_country
from app.services.lstm_predictor import LstmPricePredictor
from app.services.official_fuel_client import OfficialFuelClient
from app.services.station_recommendation import StationRecommendationService

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@router.get("/fuels")
async def fuels() -> dict[str, list[str]]:
    return {"fuels": [fuel.value for fuel in FuelType]}


@router.get("/stations/nearby", response_model=NearbyStationsResponse)
async def nearby_stations(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    fuel_type: FuelType = Query(...),
    liters: float = Query(50, gt=1, le=200),
    consumption_l_100km: float = Query(6.5, gt=1, le=30),
    radius_km: float = Query(settings.default_radius_km, gt=0.5, le=50),
    limit: int = Query(settings.default_limit, gt=1, le=100),
    country: str | None = Query(None, description="FR or ES. Auto-detected when omitted."),
) -> NearbyStationsResponse:
    async with OfficialFuelClient() as client:
        service = StationRecommendationService(client)
        try:
            return await service.nearby(
                lat=lat,
                lon=lon,
                fuel_type=fuel_type,
                liters=liters,
                consumption_l_100km=consumption_l_100km,
                radius_km=radius_km,
                limit=limit,
                country=normalize_country(country, lat, lon),
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/predictions/price", response_model=PricePredictionResponse)
async def price_prediction(
    fuel_type: FuelType = Query(...),
    station_id: str | None = Query(None),
    horizon_hours: int = Query(24, ge=1, le=168),
) -> PricePredictionResponse:
    return await LstmPricePredictor().predict(
        fuel_type=fuel_type,
        station_id=station_id,
        horizon_hours=horizon_hours,
    )
