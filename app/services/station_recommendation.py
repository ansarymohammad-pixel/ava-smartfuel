from app.schemas.station import FuelType, NearbyStationsResponse, StationChoice
from app.services.ava_score import compute_ava_score
from app.services.country import CountryCode
from app.services.geo import google_maps_navigation_url, haversine_km
from app.services.official_fuel_client import OfficialFuelClient


class StationRecommendationService:
    def __init__(self, official_client: OfficialFuelClient) -> None:
        self.official_client = official_client

    async def nearby(
        self,
        *,
        lat: float,
        lon: float,
        fuel_type: FuelType,
        liters: float,
        consumption_l_100km: float,
        radius_km: float,
        limit: int,
        country: CountryCode = CountryCode.france,
    ) -> NearbyStationsResponse:
        stations = await self.official_client.fetch_nearby(
            lat=lat,
            lon=lon,
            fuel_type=fuel_type,
            radius_km=radius_km,
            limit=limit,
            country=country,
        )
        if not stations:
            return NearbyStationsResponse(
                fuel_type=fuel_type,
                user_lat=lat,
                user_lon=lon,
                liters=liters,
                consumption_l_100km=consumption_l_100km,
                radius_km=radius_km,
                average_price_eur_l=None,
                choices=[],
            )
        distances = [haversine_km(lat, lon, station.lat, station.lon) for station in stations]
        nearest = min(distances)
        average_price = sum(station.price_eur_l for station in stations) / len(stations)
        baseline = min(station.price_eur_l for station in stations)
        choices = []
        for station, distance in zip(stations, distances, strict=True):
            detour_km = max(0.0, (distance - nearest) * 2)
            choices.append(
                StationChoice(
                    station=station,
                    distance_km=round(distance, 2),
                    google_maps_url=google_maps_navigation_url(station.lat, station.lon),
                    ava=compute_ava_score(
                        station_price=station.price_eur_l,
                        baseline_price=baseline,
                        liters=liters,
                        detour_km=detour_km,
                        consumption_l_100km=consumption_l_100km,
                        average_price=average_price,
                    ),
                )
            )
        choices.sort(key=lambda choice: (choice.station.price_eur_l, choice.distance_km))
        choices[0].best_choice = True
        return NearbyStationsResponse(
            fuel_type=fuel_type,
            user_lat=lat,
            user_lon=lon,
            liters=liters,
            consumption_l_100km=consumption_l_100km,
            radius_km=radius_km,
            average_price_eur_l=round(average_price, 3),
            choices=choices,
        )
