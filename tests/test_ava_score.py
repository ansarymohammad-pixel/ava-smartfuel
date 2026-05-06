from app.services.ava_score import compute_ava_score


def test_ava_score_rewards_savings() -> None:
    score = compute_ava_score(
        station_price=1.70,
        baseline_price=1.82,
        liters=50,
        detour_km=3,
        consumption_l_100km=6,
        average_price=1.76,
    )
    assert score.net_gain_eur > 5

