"""Sanal park simülatörü testleri."""

import json

import numpy as np
import pandas as pd
import pytest

from twin.sim.efficiency import OracleJustInTime
from twin.sim.engine import simulate_strategy_season
from twin.sim.virtual_park import (
    SensorFault,
    VirtualSensor,
    load_scenario,
    parameter_inventory,
    simulate_virtual_park,
)


def _weather(n=40, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-06-01", periods=n, freq="D")
    w = pd.DataFrame(
        {"eto_mm": rng.uniform(3, 7, n), "rain_mm": np.where(rng.random(n) < 0.2, rng.gamma(1.5, 6, n), 0.0)},
        index=idx,
    )
    w.attrs["source"] = "synthetic"
    return w


def _scenario_file(tmp_path, sensors, vegetation="turf_cool_season"):
    data = {
        "name": "test",
        "park_id": "yildiz",
        "status": "assumption",
        "zones": [
            {
                "zone_id": "A",
                "name": "a",
                "vegetation": vegetation,
                "area_m2": 2000,
                "layout": [0, 0, 10, 10],
                "sensors": sensors,
            }
        ],
    }
    p = tmp_path / "s.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return load_scenario(p)


def test_zone_matches_engine_for_same_strategy(tmp_path):
    """Sensörsüz kâhin: sanal park zonu, motorun aynı profil/havayla ürettiği sonuçla aynı."""
    from twin.config import config_for_vegetation

    sc = _scenario_file(tmp_path, [])
    w = _weather()
    run = simulate_virtual_park(sc, w, lambda _z: OracleJustInTime())
    eng, _ = simulate_strategy_season(OracleJustInTime(), w, config=config_for_vegetation("turf_cool_season"))
    np.testing.assert_allclose(run.zones["advice_gross_mm"].to_numpy(), eng["irrigation_gross_mm"].to_numpy())
    np.testing.assert_allclose(run.zones["depletion_mm"].to_numpy(), eng["depletion_mm"].to_numpy())
    assert run.zones["advice_m3"].sum() == pytest.approx(run.zones["advice_gross_mm"].sum() / 1000 * 2000)
    assert run.source == "synthetic"


def test_unverified_vegetation_is_skipped_not_invented(tmp_path):
    sc = _scenario_file(tmp_path, [], vegetation="tree")
    run = simulate_virtual_park(sc, _weather(), lambda _z: OracleJustInTime())
    assert "A" in run.skipped
    assert run.zones.empty
    inv = parameter_inventory(sc)
    assert "missing" in set(inv["durum"])


def test_sensor_faults_behave_by_day():
    rng = np.random.default_rng(0)
    drift = VirtualSensor("d", [0, 0], 0.0, SensorFault(type="drift", rate_per_day=0.001))
    assert drift.read(0.2, 100, rng) == pytest.approx(0.3)
    bias = VirtualSensor("b", [0, 0], 0.0, SensorFault(type="bias", value=0.05))
    assert bias.read(0.2, 5, rng) == pytest.approx(0.25)
    fr = VirtualSensor("f", [0, 0], 0.0, SensorFault(type="freeze", start_day=3, duration_days=2))
    assert fr.read(0.20, 3, rng) == pytest.approx(0.20)
    assert fr.read(0.10, 4, rng) == pytest.approx(0.20)  # donmuş
    assert fr.read(0.10, 5, rng) == pytest.approx(0.10)  # çözüldü
    drop = VirtualSensor("x", [0, 0], 0.0, SensorFault(type="dropout", prob=1.0))
    assert np.isnan(drop.read(0.2, 1, rng))


def test_sensor_obs_is_mean_of_valid_readings(tmp_path):
    sensors = [
        {"sensor_id": "s1", "pos": [1, 1], "noise_std": 0.0, "fault": {"type": "bias", "value": 0.02}},
        {"sensor_id": "s2", "pos": [2, 2], "noise_std": 0.0, "fault": {"type": "dropout", "prob": 1.0}},
    ]
    sc = _scenario_file(tmp_path, sensors)
    run = simulate_virtual_park(sc, _weather(), lambda _z: OracleJustInTime())
    np.testing.assert_allclose(run.zones["sensor_obs"], run.zones["theta_start"] + 0.02)


def test_shipped_scenario_loads():
    sc = load_scenario("data/scenarios/yildiz_sanal.json")
    assert sc.status == "assumption"
    assert {z.zone_id for z in sc.zones} == {"Z1", "Z2", "Z3"}
