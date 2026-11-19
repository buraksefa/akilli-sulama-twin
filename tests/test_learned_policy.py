"""Öğrenilmiş politika testleri: nedensellik (sızıntı yok), taban davranışı, DAgger, bölünme."""

import numpy as np
import pandas as pd
import pytest

from twin.config import TwinConfig
from twin.sim.efficiency import OracleJustInTime
from twin.sim.engine import simulate_strategy_season
from twin.sim.learned_policy import (
    FEATURES,
    LearnedPolicy,
    PersistenceJIT,
    _Recorder,
    leave_one_year_out,
    train_dagger,
)


def _weather(year, n=60, seed=0, eto=None, rain=None):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(f"{year}-06-01", periods=n, freq="D")
    eto = rng.uniform(3.0, 7.0, n) if eto is None else np.asarray(eto, dtype=float)
    rain = np.where(rng.random(n) < 0.15, rng.gamma(1.5, 6.0, n), 0.0) if rain is None else rain
    w = pd.DataFrame({"eto_mm": eto, "rain_mm": rain}, index=idx)
    w.attrs["source"] = "synthetic"
    return w


@pytest.fixture(scope="module")
def cfg():
    return TwinConfig()


@pytest.fixture(scope="module")
def small_model(cfg):
    return train_dagger([_weather(2001, seed=1), _weather(2002, seed=2)], cfg, iterations=1, seed=0)


def _decide_with_today(policy, today_eto, today_rain, cfg):
    """Aynı geçmiş, aynı durum; yalnız BUGÜNÜN hava değeri farklı."""
    dates = pd.date_range("2024-07-01", periods=4, freq="D")
    for i, d in enumerate(dates[:3]):
        policy.decide(i, d, pd.Series({"eto_mm": 5.0, "rain_mm": 0.0, "kc": 0.95}), 10.0, None, 0.0, cfg)
    row = pd.Series({"eto_mm": today_eto, "rain_mm": today_rain, "kc": 0.95})
    return policy.decide(3, dates[3], row, 27.0, None, 0.0, cfg)


@pytest.mark.parametrize("make", ["s5", "s6"])
def test_policies_do_not_see_todays_weather(make, cfg, small_model):
    """Sızıntı testi: bugünün ETo/yağışı değişince karar değişmemeli."""

    def new():
        return PersistenceJIT() if make == "s5" else LearnedPolicy(small_model)

    a = _decide_with_today(new(), 2.0, 0.0, cfg)
    b = _decide_with_today(new(), 9.0, 40.0, cfg)
    assert a == b


def test_persistence_equals_oracle_on_constant_dry_weather(cfg):
    """Sabit ETo ve yağışsız havada kalıcılık tahmini tam doğrudur, S5 = kâhin (ilk gün hariç)."""
    w = _weather(2024, n=60, eto=np.full(60, 5.0), rain=np.zeros(60))
    s5, _ = simulate_strategy_season(PersistenceJIT(), w, config=cfg)
    orc, _ = simulate_strategy_season(OracleJustInTime(), w, config=cfg)
    assert s5["irrigation_gross_mm"].sum() == pytest.approx(orc["irrigation_gross_mm"].sum(), abs=1e-9)
    assert (s5["ks"] >= 0.999).all()


def test_recorder_labels_are_oracle_doses(cfg):
    """DAgger etiketleri, ziyaret edilen durumda kâhinin vereceği dozdur."""
    w = _weather(2024, n=30, seed=3)
    rec = _Recorder(actor=PersistenceJIT())
    sim_df, _ = simulate_strategy_season(rec, w, config=cfg)
    oracle = OracleJustInTime()
    dr_prev = np.concatenate([[0.0], sim_df["depletion_mm"].to_numpy()[:-1]])
    for i, row in enumerate(rec.rows):
        assert row["dr_prev_mm"] == pytest.approx(dr_prev[i])
        w_row = sim_df.iloc[i][["eto_mm", "rain_mm", "kc"]]
        expected = oracle.decide(i, sim_df.index[i], w_row, dr_prev[i], None, 0.0, cfg)
        assert row["label_gross_mm"] == pytest.approx(expected)
    assert set(FEATURES) <= set(rec.rows[0])


def test_training_is_deterministic(cfg):
    seasons = [_weather(2001, seed=1), _weather(2002, seed=2)]
    x = pd.DataFrame([dict.fromkeys(FEATURES, 1.0)])
    m1 = train_dagger(seasons, cfg, iterations=1, seed=0)
    m2 = train_dagger(seasons, cfg, iterations=1, seed=0)
    assert m1.predict(x)[0] == m2.predict(x)[0]


def test_leave_one_year_out_never_trains_on_test_year(cfg):
    seasons = {2001: _weather(2001, seed=1), 2002: _weather(2002, seed=2), 2003: _weather(2003, seed=3)}
    t = leave_one_year_out(seasons, cfg, iterations=0)
    for year, grp in t.groupby("season"):
        assert str(year) not in grp["train_years"].iloc[0].split(",")
    assert {"S5", "S6", "ORACLE"} <= set(t["strategy"])
    assert (t["source"] == "synthetic").all()
