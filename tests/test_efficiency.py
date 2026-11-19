"""Verimlilik modülü testleri: kâhin JIT, LP alt sınırı, su bütçesi ve ayrıştırma."""

import numpy as np
import pandas as pd
import pytest

from twin.config import TwinConfig
from twin.model.waterbalance import compute_raw, compute_taw
from twin.sim.efficiency import (
    OracleJustInTime,
    decompose_excess,
    minimum_irrigation_lp,
    water_balance_accounting,
)
from twin.sim.engine import prepare_season_weather, simulate_strategy_season
from twin.sim.strategies import get_all_strategies


@pytest.fixture(scope="module")
def cfg():
    return TwinConfig()


@pytest.fixture(scope="module")
def raw_mm(cfg):
    taw = compute_taw(cfg.soil.theta_fc.value, cfg.soil.theta_wp.value, cfg.soil.root_depth_m.value)
    return compute_raw(taw, cfg.soil.p_depletion.value)


@pytest.fixture(scope="module")
def weather():
    return prepare_season_weather(season_year=2024, source="synthetic")


def _toy_weather(etc_mm, rain_mm):
    """Kc = 1 sabit, ETo = ETc olan küçük el-hesabı serisi."""
    idx = pd.date_range("2024-07-01", periods=len(etc_mm), freq="D")
    return pd.DataFrame({"eto_mm": etc_mm, "rain_mm": rain_mm, "kc": 1.0}, index=idx)


def test_lp_toy_hand_calculation(cfg, raw_mm):
    """Yağışsız, ETc = RAW/2 olan 4 gün: x0 = 0'dan gereken net su = 4*(RAW/2) - RAW = RAW."""
    half = raw_mm / 2.0
    res = minimum_irrigation_lp(_toy_weather([half] * 4, [0.0] * 4), cfg)
    assert res.total_net_mm == pytest.approx(raw_mm, abs=1e-6)
    assert res.total_gross_mm == pytest.approx(raw_mm / cfg.irrigation.efficiency.value, abs=1e-6)


def test_oracle_matches_lp_and_is_stress_free(cfg, raw_mm, weather):
    """Önerme 1'in sayısal kontrolü: JIT toplamı = LP en iyisi, sezon boyunca Ks = 1."""
    sim_df, metrics = simulate_strategy_season(OracleJustInTime(), weather, config=cfg)
    lp = minimum_irrigation_lp(sim_df, cfg)

    assert metrics.stress_days_count == 0
    assert sim_df["depletion_mm"].max() <= raw_mm + 1e-9
    assert sim_df["irrigation_gross_mm"].sum() == pytest.approx(lp.total_gross_mm, rel=1e-6)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_oracle_matches_lp_with_rain_and_runoff(cfg, seed):
    """Şiddetli yağış (yüzey akışı) ve kuru dönemler içeren rastgele seride de JIT = LP."""
    rng = np.random.default_rng(seed)
    n = 120
    rain = np.where(rng.random(n) < 0.2, rng.gamma(1.5, 12.0, n), 0.0)
    w = _toy_weather(rng.uniform(2.0, 7.0, n), rain)
    sim_df, _ = simulate_strategy_season(OracleJustInTime(), w, config=cfg)
    # Motor Kc'yi aya göre yeniden atar; LP'ye motorun kullandığı Kc ile aynı seriyi ver.
    lp = minimum_irrigation_lp(sim_df, cfg)
    assert sim_df["irrigation_gross_mm"].sum() == pytest.approx(lp.total_gross_mm, rel=1e-6, abs=1e-6)


def test_minimum_water_nonincreasing_in_allowed_depletion(cfg, weather):
    """İzin verilen tükenme D arttıkça (toprak daha kuru tutulur) gereken su azalır ya da aynı kalır."""
    totals = [
        minimum_irrigation_lp(weather, cfg, target_fraction_of_raw=f).total_gross_mm
        for f in (0.25, 0.5, 0.75, 1.0)
    ]
    assert all(b <= a + 1e-6 for a, b in zip(totals, totals[1:]))


def test_no_strategy_beats_oracle_without_stress(cfg, weather):
    """Stressiz kalan hiçbir strateji kâhinden az su kullanamaz (alt sınır)."""
    oracle_df, _ = simulate_strategy_season(OracleJustInTime(), weather, config=cfg)
    w_star = oracle_df["irrigation_gross_mm"].sum()
    for strat in get_all_strategies().values():
        sim_df, m = simulate_strategy_season(strat, weather, config=cfg)
        if m.stress_days_count == 0:
            assert sim_df["irrigation_gross_mm"].sum() >= w_star - 1e-6


def test_water_balance_closes_for_all_strategies(cfg, weather):
    for strat in list(get_all_strategies().values()) + [OracleJustInTime()]:
        sim_df, _ = simulate_strategy_season(strat, weather, config=cfg)
        acc = water_balance_accounting(sim_df)
        assert acc["closure_error_mm"] == pytest.approx(0.0, abs=1e-6)
        assert 0.0 <= acc["relative_et_deficit"] <= 1.0


def test_decompose_excess_identity(cfg, weather):
    """Fazla brüt su = ETa + derin sızma + depolama terimlerinin toplamı."""
    eff = cfg.irrigation.efficiency.value
    oracle_df, _ = simulate_strategy_season(OracleJustInTime(), weather, config=cfg)
    s0_df, _ = simulate_strategy_season(get_all_strategies()["S0"], weather, config=cfg)
    dec = decompose_excess(s0_df, oracle_df, eff)
    parts = dec["from_eta_mm"] + dec["from_deep_percolation_mm"] + dec["from_storage_mm"]
    assert dec["excess_gross_mm"] == pytest.approx(parts, abs=1e-6)


def test_oracle_rejects_invalid_target():
    with pytest.raises(ValueError):
        OracleJustInTime(target_fraction_of_raw=1.5)


def test_vegetation_profiles_are_verified_fao56():
    """Profil değerleri FAO-56 Tablo 12/22'den; her parametre kaynaklı ve 'verified'."""
    from twin.config import VEGETATION_PROFILES, VerificationStatus

    cool = VEGETATION_PROFILES["turf_cool_season"]
    assert (cool.kc_initial.value, cool.kc_mid.value, cool.kc_end.value) == (0.90, 0.95, 0.95)
    assert cool.p_depletion.value == 0.40
    warm = VEGETATION_PROFILES["turf_warm_season"]
    assert (warm.kc_initial.value, warm.kc_mid.value, warm.kc_end.value) == (0.80, 0.85, 0.85)
    assert warm.p_depletion.value == 0.50
    for prof in VEGETATION_PROFILES.values():
        for item in (prof.kc_initial, prof.kc_mid, prof.kc_end, prof.root_depth_m, prof.p_depletion):
            assert item.status == VerificationStatus.VERIFIED
            assert "FAO-56" in item.source


def test_config_for_vegetation_applies_profile_and_copies(cfg):
    from twin.config import config_for_vegetation

    veg = config_for_vegetation("turf_warm_season", cfg)
    assert veg.crop.kc_mid.value == 0.85
    assert veg.soil.p_depletion.value == 0.50
    assert veg.soil.root_depth_m.value == 0.5
    assert veg.soil.theta_fc.value == cfg.soil.theta_fc.value  # toprak temelden gelir
    assert cfg.soil.p_depletion.value == 0.40  # temel yapılandırma değişmedi
    assert cfg.crop.kc_mid.value == 0.95


def test_default_config_matches_fao56_cool_season_turf(cfg):
    """Varsayılan çim parametreleri FAO-56 serin iklim çimi profiliyle birebir aynı."""
    from twin.config import VEGETATION_PROFILES

    prof = VEGETATION_PROFILES["turf_cool_season"]
    assert cfg.crop.kc_initial.value == prof.kc_initial.value
    assert cfg.crop.kc_mid.value == prof.kc_mid.value
    assert cfg.crop.kc_end.value == prof.kc_end.value
    assert cfg.soil.root_depth_m.value == prof.root_depth_m.value
    assert cfg.soil.p_depletion.value == prof.p_depletion.value


def test_config_for_vegetation_rejects_unverified_type():
    from twin.config import config_for_vegetation

    with pytest.raises(KeyError, match="doğrulanmış"):
        config_for_vegetation("tree")


def test_engine_uses_config_kc(weather):
    """Motor Kc'yi verilen yapılandırmadan almalı (önceden sabit varsayılan kullanılıyordu)."""
    from twin.config import config_for_vegetation

    veg = config_for_vegetation("turf_warm_season")
    sim_df, _ = simulate_strategy_season(OracleJustInTime(), weather, config=veg)
    assert sim_df.loc[sim_df.index.month == 7, "kc"].unique().tolist() == [0.85]


def test_park_zone_requirement_flags_missing_profile(weather):
    from twin.data.parks import IrrigationZone
    from twin.sim.efficiency import park_zone_requirement

    zones = [
        IrrigationZone("z1", "p", "lawn", "sprinkler", 2000.0),
        IrrigationZone("z2", "p", "tree", "drip", 1000.0),
    ]
    out = park_zone_requirement(weather, zones).set_index("zone_id")
    assert out.loc["z1", "status"] == "ok"
    assert out.loc["z1", "min_gross_m3"] == pytest.approx(out.loc["z1", "min_gross_mm"] * 2.0)
    assert out.loc["z2", "status"] == "no_verified_profile"
    assert np.isnan(out.loc["z2", "min_gross_mm"])
