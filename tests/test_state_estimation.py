"""S5 durum kestiricisi testleri: nedensellik, true = S5, openloop = gerçek, tohum, motor seed."""

import numpy as np
import pandas as pd
import pytest

from twin.config import TwinConfig
from twin.sim.engine import prepare_season_weather, simulate_strategy_season
from twin.sim.learned_policy import (
    ESTIMATORS,
    EstimatedPersistenceJIT,
    PersistenceJIT,
    noisy_state_experiment,
)
from twin.sim.strategies import get_all_strategies


def _weather(n=60, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-06-01", periods=n, freq="D")
    rain = np.where(rng.random(n) < 0.15, rng.gamma(1.5, 6.0, n), 0.0)
    w = pd.DataFrame({"eto_mm": rng.uniform(3.0, 7.0, n), "rain_mm": rain}, index=idx)
    w.attrs["source"] = "synthetic"
    return w


@pytest.fixture(scope="module")
def cfg():
    return TwinConfig()


@pytest.mark.parametrize("estimator", ESTIMATORS)
def test_estimators_do_not_see_todays_weather(estimator, cfg):
    """Sızıntı testi: aynı geçmiş, durum ve sensör; yalnız bugünün ETo/yağışı farklı -> aynı karar."""

    def run(today_eto, today_rain):
        pol = EstimatedPersistenceJIT(estimator, seed=3)
        dates = pd.date_range("2024-07-01", periods=4, freq="D")
        for i, d in enumerate(dates[:3]):
            row = pd.Series({"eto_mm": 5.0, "rain_mm": 0.0, "kc": 0.95})
            pol.decide(i, d, row, 10.0 + 5 * i, 0.25, 0.0, cfg)
        row = pd.Series({"eto_mm": today_eto, "rain_mm": today_rain, "kc": 0.95})
        return pol.decide(3, dates[3], row, 27.0, 0.22, 0.0, cfg)

    assert run(2.0, 0.0) == run(9.0, 40.0)


def test_true_estimator_equals_s5(cfg):
    w = _weather()
    a, _ = simulate_strategy_season(PersistenceJIT(0.9), w, config=cfg)
    b, _ = simulate_strategy_season(EstimatedPersistenceJIT("true", 0.9), w, config=cfg)
    np.testing.assert_array_equal(a["irrigation_gross_mm"].to_numpy(), b["irrigation_gross_mm"].to_numpy())


def test_openloop_tracks_true_state_without_model_error(cfg):
    """b = 1 ve model = gerçek iken sensörsüz açık döngü kestirim gerçek Dr ile aynı."""
    pol = EstimatedPersistenceJIT("openloop", 0.9, eto_bias_factor=1.0)
    simulate_strategy_season(pol, _weather(), config=cfg)
    err = pol.estimation_error()
    assert err["est_rmse_mm"] == pytest.approx(0.0, abs=1e-9)


def test_openloop_drifts_with_biased_eto(cfg):
    """b = 1,1 (ikiz ETo'yu fazla görüyor) -> kestirim gerçekten kuru, yanlılık pozitif."""
    pol = EstimatedPersistenceJIT("openloop", 0.9, eto_bias_factor=1.1)
    simulate_strategy_season(pol, _weather(), config=cfg)
    assert pol.estimation_error()["est_bias_mm"] > 0.0


@pytest.mark.parametrize("estimator", ["sensor", "enkf"])
def test_seeded_runs_are_deterministic(estimator, cfg):
    w = _weather()

    def run(seed):
        df, _ = simulate_strategy_season(
            EstimatedPersistenceJIT(estimator, 0.9, seed=seed), w, config=cfg, seed=seed
        )
        return df["irrigation_gross_mm"].to_numpy()

    np.testing.assert_array_equal(run(5), run(5))
    assert not np.array_equal(run(5), run(6))


def test_engine_default_seed_unchanged(cfg):
    """seed parametresi eklenmeden önceki davranış: varsayılan = 42."""
    w = prepare_season_weather(season_year=2024, source="synthetic")
    for strat_key in ("S1", "S4"):
        a, _ = simulate_strategy_season(get_all_strategies()[strat_key], w, config=cfg)
        b, _ = simulate_strategy_season(get_all_strategies()[strat_key], w, config=cfg, seed=42)
        np.testing.assert_array_equal(a["sensor_obs"].to_numpy(), b["sensor_obs"].to_numpy())
        np.testing.assert_array_equal(
            a["irrigation_gross_mm"].to_numpy(), b["irrigation_gross_mm"].to_numpy()
        )


def test_invalid_estimator_rejected():
    with pytest.raises(ValueError):
        EstimatedPersistenceJIT("magic")


def test_noisy_state_experiment_shape(cfg):
    t = noisy_state_experiment({2024: _weather()}, cfg, biases=(1.0,), margins=(0.9,), seeds=(0, 1))
    assert len(t) == 2 * (2 + len(ESTIMATORS))
    assert (t["source"] == "synthetic").all()
    s5 = t[t["strategy"] == "S5"]
    assert set(s5["estimator"]) == set(ESTIMATORS)
    assert np.allclose(t["excess_vs_oracle_mm"], t["irrigation_gross_mm"] - t["oracle_gross_mm"])
