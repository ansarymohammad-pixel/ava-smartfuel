from app.schemas.station import AvaScore, StationType
from app.services.station_type import station_type_price_penalty


def compute_ava_score(
    *,
    station_price: float,
    baseline_price: float,
    liters: float,
    detour_km: float,
    consumption_l_100km: float,
    average_price: float,
    station_type: StationType = StationType.city,
) -> AvaScore:
    full_tank_cost = station_price * liters
    detour_cost = detour_km * consumption_l_100km * average_price / 100
    type_penalty = station_type_price_penalty(station_type) * liters
    estimated_savings = max(0.0, (baseline_price - station_price) * liters)
    net_gain = estimated_savings - detour_cost - type_penalty
    score = round(
        max(0.0, min(45.0, net_gain * 7))
        + max(0.0, 35.0 - detour_km * 7)
        + max(0.0, 20.0 - detour_km * 3)
    )
    if station_type == StationType.motorway and net_gain < 1.0:
        label = "Autoroute"
        reason = "Station pratique, mais prix souvent plus eleve sur autoroute."
    elif net_gain >= 1.0 and station_price < baseline_price:
        label = "Economique"
        reason = "Le prix compense le detour estime."
    elif detour_km <= 1.0:
        label = "Proche"
        reason = "La station demande tres peu de detour."
    else:
        label = "Rapide"
        reason = "Choix correct, mais le gain net reste limite."
    return AvaScore(
        label=label,
        score=max(0, min(100, score)),
        full_tank_cost_eur=round(full_tank_cost, 2),
        detour_cost_eur=round(detour_cost + type_penalty, 2),
        estimated_savings_eur=round(estimated_savings, 2),
        net_gain_eur=round(net_gain, 2),
        detour_km=round(detour_km, 2),
        reason=reason,
    )
