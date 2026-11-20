"""Sanal dünya testleri: poligon, belirlenimcilik, katman ayrımı (ikiz dünyayı görmez), kütle dengesi."""

import json

import numpy as np
import pandas as pd
import pytest

from twin.config import TwinConfig
from twin.sim.virtual_world import (
    STRATEGIES,
    ZoneTwin,
    build_world,
    load_world_spec,
    run_world,
    summarize_run,
)

SPEC = "data/scenarios/yildiz_dunya.json"
GEOJSON = "data/public/parks.geojson"


@pytest.fixture(scope="module")
def world():
    return build_world(load_world_spec(SPEC), GEOJSON)


def _weather(n=40, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-06-01", periods=n, freq="D")
    w = pd.DataFrame(
        {"eto_mm": rng.uniform(3, 7, n), "rain_mm": np.where(rng.random(n) < 0.2, rng.gamma(1.5, 6, n), 0.0)},
        index=idx,
    )
    w.attrs["source"] = "synthetic"
    return w


def test_grid_area_matches_polygon(world):
    """İç hücre alanı, İBB poligon alanının (389.760 m²) %2'si içinde."""
    props = next(
        f["properties"] for f in json.load(open(GEOJSON))["features"] if f["properties"]["id"] == "yildiz"
    )
    area = len(world.veg_c) * world.cell_area_m2
    assert area == pytest.approx(props["area_m2"], rel=0.02)


def test_world_is_deterministic_and_fractions_hold(world):
    w2 = build_world(load_world_spec(SPEC), GEOJSON)
    np.testing.assert_array_equal(world.veg_c, w2.veg_c)
    np.testing.assert_array_equal(world.fc_c, w2.fc_c)
    spec = load_world_spec(SPEC)["vegetation"]
    for i, key in enumerate(["turf", "tree", "shrub", "flower"]):
        assert np.mean(world.veg_c == i) == pytest.approx(spec[key]["fraction"], abs=0.01)
    assert (world.wp_c < world.fc_c).all()


def test_every_zone_has_one_vegetation_and_sensors(world):
    for zi, z in enumerate(world.zones):
        assert len(set(world.veg_c[world.zone_c == zi])) == 1
    assert {s.zone_index for s in world.sensors} == set(range(len(world.zones)))


def test_twin_does_not_see_todays_weather(world):
    """Sızıntı testi: ikiz kararı bugünün ETo/yağışından bağımsızdır."""
    cfg = TwinConfig()
    spec = load_world_spec(SPEC)
    yesterday = pd.Series({"eto_mm": 5.0, "rain_mm": 0.0}, name=pd.Timestamp("2024-07-01"))
    doses = []
    for _ in range(2):
        tw = ZoneTwin(world.zones[0], spec, cfg, "jit", "model", 0.9, seed=0)
        tw.dr_hat = 25.0
        doses.append(tw.decide(5, pd.Timestamp("2024-07-02"), yesterday, None))
    assert doses[0] == doses[1]


def test_world_outputs_are_finite_and_bounded(world):
    """Sonuçlar sonlu; strese giren alan payı [0, 1] aralığında."""
    w = _weather()
    run = run_world(world, w, "MODEL")
    s0 = run_world(world, w, "S0")
    for r in (run, s0):
        assert r.water_m3.sum() >= 0
        assert np.isfinite(r.dr_true).all()
        assert 0.0 <= r.stressed_area_frac.min() <= r.stressed_area_frac.max() <= 1.0


@pytest.mark.parametrize("key", list(STRATEGIES))
def test_all_strategies_run_and_are_seeded(world, key):
    w = _weather(30)
    a = summarize_run(run_world(world, w, key, sensor_seed=3))
    b = summarize_run(run_world(world, w, key, sensor_seed=3))
    assert a == pytest.approx(b, nan_ok=True)
    assert run_world(world, w, key).source == "synthetic"


def test_zones_have_irrigation_system_and_runtime(world):
    """Her zonun bir sulama sistemi var; çalışma süresi = doz / uygulama hızı."""
    from twin.sim.virtual_world import runtime_minutes

    assert {z.irrigation for z in world.zones} <= {"yağmurlama", "damla"}
    dose = np.full(len(world.zones), 10.0)
    mins = runtime_minutes(world, dose)
    rates = np.array([z.application_rate_mm_h for z in world.zones])
    np.testing.assert_allclose(mins, 10.0 / rates * 60.0)
