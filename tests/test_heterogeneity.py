"""Zon içi farklılık deneyi: sensör yerleşimi, zon kâhini ve deney tablosu."""

import numpy as np
import pandas as pd
import pytest

from twin.sim.heterogeneity import heterogeneity_experiment, summarize_experiment, world_variant
from twin.sim.virtual_world import build_world, load_world_spec, run_world, summarize_run

SPEC = "data/scenarios/yildiz_dunya.json"
GEOJSON = "data/public/parks.geojson"


@pytest.fixture(scope="module")
def spec():
    return load_world_spec(SPEC)


def _weather(n=45, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-06-15", periods=n, freq="D")
    w = pd.DataFrame(
        {
            "eto_mm": rng.uniform(4, 7, n),
            "rain_mm": np.where(rng.random(n) < 0.15, rng.gamma(1.5, 6, n), 0.0),
        },
        index=idx,
    )
    w.attrs["source"] = "synthetic"
    return w


def _days_to_raw(world):
    return world.raw_c / (world.kc_c[:, 1] * world.micro_c)


def test_variant_keeps_world_fields_and_fault_types(spec):
    """Yerleşim değişince dünya alanları ve sensör arıza türleri aynı kalır; yalnız konumlar değişir."""
    a = build_world(world_variant(spec, (2, 2), "random"), GEOJSON)
    b = build_world(world_variant(spec, (2, 2), "critical"), GEOJSON)
    np.testing.assert_array_equal(a.fc_c, b.fc_c)
    np.testing.assert_array_equal(a.zone_c, b.zone_c)
    assert [s.sensor.fault.type for s in a.sensors] == [s.sensor.fault.type for s in b.sensors]
    assert spec["zone_blocks"] == [2, 2] and "sensor_placement" not in spec  # kopya, özgün değişmedi


def test_critical_sensor_sits_in_zone_most_critical_cell(spec):
    world = build_world(world_variant(spec, (3, 3), "critical"), GEOJSON)
    d = _days_to_raw(world)
    for s in world.sensors:
        cells = np.flatnonzero(world.zone_c == s.zone_index)
        assert world.zone_c[s.cell] == s.zone_index
        k = sum(t.zone_index == s.zone_index for t in world.sensors)
        assert d[s.cell] <= np.sort(d[cells])[k - 1] + 1e-12  # zonun en kritik k hücresinden biri


def test_unknown_placement_rejected(spec):
    with pytest.raises(ValueError):
        build_world(world_variant(spec, (2, 2), "best"), GEOJSON)


def test_finer_zones_increase_zone_and_sensor_count(spec):
    small = build_world(world_variant(spec, (1, 1), "random"), GEOJSON)
    big = build_world(world_variant(spec, (4, 4), "random"), GEOJSON)
    assert len(small.zones) == 4
    assert len(big.zones) > len(small.zones) and len(big.sensors) > len(small.sensors)


def test_zone_oracle_is_stress_free_and_finer_zones_need_less_water(spec):
    """Kâhin (margin 1) hiçbir hücreyi strese sokmaz; zonlar inceldikçe gereken su artmaz."""
    w = _weather()
    water = []
    for layout in [(1, 1), (2, 2), (4, 4)]:
        world = build_world(world_variant(spec, layout, "random"), GEOJSON)
        r = run_world(world, w, "ORACLE", margin=1.0)
        assert r.stressed_area_frac.max() == 0.0
        water.append(r.water_m3.sum())
    assert water[0] >= water[1] - 1e-6 >= water[2] - 2e-6


def test_oracle_is_skipped_by_estimation_error(spec):
    world = build_world(world_variant(spec, (2, 2), "random"), GEOJSON)
    s = summarize_run(run_world(world, _weather(20), "ORACLE", margin=1.0))
    assert np.isnan(s["kestirim_rmse_mm"])


def test_experiment_table_shape_and_labels(spec):
    df = heterogeneity_experiment(
        spec,
        GEOJSON,
        _weather(20),
        zone_blocks_list=[(1, 1), (2, 2)],
        margins=[0.9, 0.5],
        sensor_strategies=["SENSOR"],
        seeds=range(2),
    )
    # düzen başına: 1 kâhin + 2 MODEL + 2 yerleşim × 1 strateji × 2 pay × 2 tohum = 11
    assert len(df) == 2 * 11
    assert set(df["kaynak"]) == {"synthetic_world+synthetic"}
    summ = summarize_experiment(df)
    assert summ.loc[summ["strateji"] == "ORACLE", "su_kahine_orani"].eq(1.0).all()
    assert summ.loc[summ["strateji"] == "SENSOR", "tohum_sayisi"].eq(2).all()
