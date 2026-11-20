"""Tahmin yükleyici (ağsız) ve tahmine dayalı sulama planı testleri."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from twin.data.forecast import parse_open_meteo_daily
from twin.sim.virtual_world import build_world, load_world_spec, plan_from_forecast

SPEC = "data/scenarios/yildiz_dunya.json"
GEOJSON = "data/public/parks.geojson"


def _payload(days, eto, rain, prob):
    return {
        "latitude": 41.03,
        "longitude": 29.02,
        "daily": {
            "time": [d.strftime("%Y-%m-%d") for d in days],
            "et0_fao_evapotranspiration": eto,
            "precipitation_sum": rain,
            "precipitation_probability_max": prob,
            "temperature_2m_max": [25.0] * len(days),
            "temperature_2m_min": [15.0] * len(days),
        },
    }


def _weather(n_past=40, n_fc=7, fc_eto=6.0, fc_rain=0.0, fc_prob=0.0):
    days = pd.date_range("2024-06-01", periods=n_past + n_fc, freq="D")
    rng = np.random.default_rng(0)
    eto = list(rng.uniform(4, 7, n_past)) + [fc_eto] * n_fc
    rain = [0.0] * n_past + [fc_rain] * n_fc
    prob = [None] * n_past + [fc_prob] * n_fc
    return parse_open_meteo_daily(_payload(days, eto, rain, prob), today=days[n_past].date())


@pytest.fixture(scope="module")
def world():
    return build_world(load_world_spec(SPEC), GEOJSON)


def test_parse_marks_forecast_and_sources():
    days = pd.date_range("2026-11-18", periods=4, freq="D")
    df = parse_open_meteo_daily(
        _payload(days, [1, 2, 3, 4], [0, 5, 0, 1], [0, 90, 10, 50]), today=date(2026, 11, 20)
    )
    assert df["is_forecast"].tolist() == [False, False, True, True]
    assert set(df["source"]) == {"open_meteo_past", "open_meteo_forecast"}
    assert df.loc[~df["is_forecast"], "rain_prob_pct"].eq(100.0).all()
    assert df["eto_mm"].tolist() == [1.0, 2.0, 3.0, 4.0]


def test_plan_covers_forecast_days_for_every_zone(world):
    wx = _weather()
    _, plan = plan_from_forecast(world, wx, "MODEL")
    assert len(plan) == len(world.zones) * 7
    assert plan["time"].min() == wx.index[wx["is_forecast"]][0]
    rates = plan["zone"].map({z.zone_id: z.application_rate_mm_h for z in world.zones})
    np.testing.assert_allclose(plan["minutes"], plan["dose_mm"] / rates * 60.0)


def test_certain_heavy_rain_forecast_suppresses_irrigation(world):
    """Kesin (%100) ve yoğun yağış tahmininde ikiz sulama planlamaz; kuru sıcak tahminde planlar."""
    _, wet = plan_from_forecast(world, _weather(fc_eto=1.0, fc_rain=20.0, fc_prob=100.0), "MODEL")
    _, dry = plan_from_forecast(world, _weather(fc_eto=7.0, fc_rain=0.0, fc_prob=0.0), "MODEL")
    assert wet["water_m3"].sum() < dry["water_m3"].sum()
    assert wet.groupby("time")["water_m3"].sum().iloc[1:].eq(0.0).all()


def test_rain_probability_weights_expected_rain(world):
    """Aynı yağış miktarında olasılık düştükçe plan daha fazla su verir (beklenen yağış azalır)."""
    sure = plan_from_forecast(world, _weather(fc_rain=8.0, fc_prob=100.0), "MODEL")[1]["water_m3"].sum()
    unlikely = plan_from_forecast(world, _weather(fc_rain=8.0, fc_prob=10.0), "MODEL")[1]["water_m3"].sum()
    assert unlikely > sure


def test_fixed_schedule_ignores_forecast(world):
    a = plan_from_forecast(world, _weather(fc_rain=30.0, fc_prob=100.0), "S0")[1]["water_m3"].sum()
    b = plan_from_forecast(world, _weather(fc_rain=0.0, fc_prob=0.0), "S0")[1]["water_m3"].sum()
    assert a == pytest.approx(b)
