import time
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import settings
from app.schemas.prediction import PricePredictionResponse
from app.schemas.station import FuelType, NearbyStationsResponse
from app.services.country import normalize_country
from app.services.lstm_predictor import LstmPricePredictor
from app.services.official_fuel_client import OfficialFuelClient
from app.services.station_recommendation import StationRecommendationService
from app.services.user_store import (
    CurrentUser,
    connection,
    hash_password,
    init_db,
    read_token,
    user_response,
    verify_password,
)

router = APIRouter()

_NEARBY_CACHE: dict[tuple[object, ...], tuple[float, NearbyStationsResponse]] = {}


class AuthRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=6, max_length=128)
    language: str = "fr"


class ProfileUpdate(BaseModel):
    preferred_fuel: str = "SP95-E10"
    consumption_l_100km: float = Field(6.5, gt=0, le=30)
    tank_liters: float = Field(50, gt=1, le=200)
    language: str = "fr"


class FavoriteRequest(BaseModel):
    station_id: str
    station_name: str
    brand: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    fuel_type: str
    price_eur_l: float | None = None
    lat: float | None = None
    lon: float | None = None


class PriceAlertRequest(BaseModel):
    station_id: str | None = None
    fuel_type: str
    target_price: float = Field(gt=0, le=10)


def current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    user = read_token(authorization.split(" ", 1)[1].strip())
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@router.get("/fuels")
async def fuels() -> dict[str, list[str]]:
    return {"fuels": [fuel.value for fuel in FuelType]}


@router.post("/auth/register")
async def register(payload: AuthRequest) -> dict[str, object]:
    init_db()
    email = payload.email.lower().strip()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Invalid email")
    with connection() as conn:
        with conn.cursor() as cur:
            existing = cur.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail="Email already exists")
            row = cur.execute(
                "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id",
                (email, hash_password(payload.password)),
            ).fetchone()
            user_id = str(row["id"])
            cur.execute(
                """
                INSERT INTO user_profiles (user_id, language)
                VALUES (%s, %s)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (user_id, payload.language),
            )
        conn.commit()
    return user_response(user_id=user_id, email=email)


@router.post("/auth/login")
async def login(payload: AuthRequest) -> dict[str, object]:
    init_db()
    email = payload.email.lower().strip()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Invalid email")
    with connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute("SELECT id, password_hash FROM users WHERE email = %s", (email,)).fetchone()
    if not row or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return user_response(user_id=str(row["id"]), email=email)


@router.post("/auth/refresh")
async def refresh(user: CurrentUser = Depends(current_user)) -> dict[str, object]:
    return user_response(user_id=user.id, email=user.email)


@router.get("/auth/me")
async def me(user: CurrentUser = Depends(current_user)) -> dict[str, object]:
    return {"id": user.id, "email": user.email}


@router.get("/profile")
async def get_profile(user: CurrentUser = Depends(current_user)) -> dict[str, object]:
    init_db()
    with connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                SELECT preferred_fuel, consumption_l_100km, tank_liters, language
                FROM user_profiles
                WHERE user_id = %s
                """,
                (user.id,),
            ).fetchone()
    return row or {
        "preferred_fuel": "SP95-E10",
        "consumption_l_100km": 6.5,
        "tank_liters": 50,
        "language": "fr",
    }


@router.put("/profile")
async def update_profile(payload: ProfileUpdate, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    init_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_profiles (user_id, preferred_fuel, consumption_l_100km, tank_liters, language)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    preferred_fuel = EXCLUDED.preferred_fuel,
                    consumption_l_100km = EXCLUDED.consumption_l_100km,
                    tank_liters = EXCLUDED.tank_liters,
                    language = EXCLUDED.language,
                    updated_at = now()
                """,
                (user.id, payload.preferred_fuel, payload.consumption_l_100km, payload.tank_liters, payload.language),
            )
        conn.commit()
    return {"status": "ok"}


@router.get("/favorites")
async def get_favorites(user: CurrentUser = Depends(current_user)) -> list[dict[str, object]]:
    init_db()
    with connection() as conn:
        with conn.cursor() as cur:
            rows = cur.execute(
                """
                SELECT station_id, station_name, brand, fuel_type, country, lat, lon, price_eur_l
                FROM favorite_stations
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (user.id,),
            ).fetchall()
    return list(rows)


@router.post("/favorites")
async def save_favorite(payload: FavoriteRequest, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    init_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO favorite_stations (
                    user_id, station_id, station_name, brand, address, city, country,
                    fuel_type, price_eur_l, lat, lon
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, station_id, fuel_type) DO UPDATE SET
                    station_name = EXCLUDED.station_name,
                    brand = EXCLUDED.brand,
                    address = EXCLUDED.address,
                    city = EXCLUDED.city,
                    country = EXCLUDED.country,
                    price_eur_l = EXCLUDED.price_eur_l,
                    lat = EXCLUDED.lat,
                    lon = EXCLUDED.lon
                """,
                (
                    user.id,
                    payload.station_id,
                    payload.station_name,
                    payload.brand,
                    payload.address,
                    payload.city,
                    payload.country,
                    payload.fuel_type,
                    payload.price_eur_l,
                    payload.lat,
                    payload.lon,
                ),
            )
        conn.commit()
    return {"status": "ok"}


@router.post("/alerts")
async def save_price_alert(payload: PriceAlertRequest, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    init_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO price_alerts (user_id, station_id, fuel_type, target_price, active)
                VALUES (%s, %s, %s, %s, true)
                """,
                (user.id, payload.station_id, payload.fuel_type, payload.target_price),
            )
        conn.commit()
    return {"status": "ok"}


@router.get("/stations/nearby", response_model=NearbyStationsResponse)
async def nearby_stations(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    fuel_type: FuelType = Query(...),
    liters: float = Query(50, gt=1, le=200),
    consumption_l_100km: float = Query(6.5, gt=1, le=30),
    radius_km: float = Query(settings.default_radius_km, gt=0.5, le=50),
    limit: int = Query(settings.default_limit, gt=1, le=100),
    country: str | None = Query(None, description="FR, ES or IT. Auto-detected when omitted."),
) -> NearbyStationsResponse:
    normalized_country = normalize_country(country, lat, lon)
    cache_key = (
        round(lat, 4),
        round(lon, 4),
        fuel_type.value,
        round(liters, 1),
        round(consumption_l_100km, 1),
        round(radius_km, 1),
        limit,
        normalized_country.value,
    )
    cached = _NEARBY_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < settings.nearby_cache_ttl_seconds:
        return cached[1].model_copy(deep=True)

    async with OfficialFuelClient() as client:
        service = StationRecommendationService(client)
        try:
            response = await service.nearby(
                lat=lat,
                lon=lon,
                fuel_type=fuel_type,
                liters=liters,
                consumption_l_100km=consumption_l_100km,
                radius_km=radius_km,
                limit=limit,
                country=normalized_country,
            )
            _NEARBY_CACHE[cache_key] = (time.monotonic(), response.model_copy(deep=True))
            return response
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
