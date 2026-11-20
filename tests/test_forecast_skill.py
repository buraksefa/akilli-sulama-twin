"""Tahmin isabeti ve karar değeri testleri (ağsız)."""

import numpy as np
import pandas as pd
import pytest

from twin.data.forecast import parse_previous_runs_hourly
from twin.sim.forecast_skill import decision_value, skill_table
from twin.sim.virtual_world import build_world, load_world_spec, run_world, summarize_run


def _payload(hours, leads, value=0.25):
    h = {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in hours]}
    for k in leads:
        sfx = "" if k == 0 else f"_previous_day{k}"
        h[f"et0_fao_evapotranspiration{sfx}"] = [value] * len(hours)
        h[f"precipitation{sfx}"] = [0.0] * len(hours)
    return {"latitude": 41.03, "longitude": 29.02, "hourly": h}


def test_previous_runs_hourly_to_daily_sums_and_flags_missing_hours():
    hours = pd.date_range("2024-07-01", periods=48, freq="h")
    payload = _payload(hours, range(0, 3))
    payload["hourly"]["et0_fao_evapotranspiration_previous_day2"][30] = None
    d = parse_previous_runs_hourly(payload, range(0, 3))
    assert d["eto_d1"].tolist() == pytest.approx([6.0, 6.0])
    assert d["eto_d2"].isna().tolist() == [False, True]
    assert d.attrs["source"] == "open_meteo_previous_runs"


def _reference(n=60, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-06-01", periods=n, freq="D", tz="UTC")
    ref = pd.DataFrame(
        {
            "eto_mm": rng.uniform(3, 7, n),
            "rain_mm": np.where(rng.random(n) < 0.25, rng.gamma(1.5, 6, n), 0.0),
        },
        index=idx,
    )
    ref.attrs["source"] = "synthetic"
    return ref


def _perfect_forecast(ref, leads=range(0, 8)):
    idx = ref.index.tz_localize(None)
    cols = {}
    for k in leads:
        cols[f"eto_d{k}"] = ref["eto_mm"].to_numpy()
        cols[f"rain_d{k}"] = ref["rain_mm"].to_numpy()
    return pd.DataFrame(cols, index=idx)


def test_skill_of_perfect_forecast_aligns_timezones():
    """Saat dilimli referans ile dilimsiz tahmin eşleşir; kusursuz tahminde hata 0, olay yakalama tam."""
    ref = _reference()
    t = skill_table(_perfect_forecast(ref), ref).set_index("tahmin")
    row = t.loc["1 gün önce"]
    assert row["eto_n"] == len(ref)
    assert row["eto_mae_mm"] == pytest.approx(0.0)
    assert row["yagis_mae_mm"] == pytest.approx(0.0)
    assert row["pod_1mm"] == pytest.approx(1.0) and row["far_1mm"] == pytest.approx(0.0)
    assert "kalıcılık (dün)" in t.index


def test_run_world_without_forecast_is_unchanged():
    """forecast=None, önceki kalıcılık davranışıyla aynı sonucu verir."""
    w = build_world(load_world_spec("data/scenarios/yildiz_dunya.json"), "data/public/parks.geojson")
    ref = _reference(30)
    a = summarize_run(run_world(w, ref, "MODEL"))
    b = summarize_run(run_world(w, ref, "MODEL", forecast=None))
    assert a == pytest.approx(b)


def test_decision_value_levels_and_forecast_is_used():
    w = build_world(load_world_spec("data/scenarios/yildiz_dunya.json"), "data/public/parks.geojson")
    ref = _reference(40)
    dv = decision_value(w, ref, _perfect_forecast(ref), strategies=("MODEL",), seeds=range(2))
    assert set(dv["bilgi"]) == {"kalıcılık", "tahmin (1 gün önce)", "kusursuz tahmin"}
    g = dv.groupby("bilgi")["su_m3"].mean()
    # kusursuz tahmin bu testte "1 gün önce" tahminiyle aynı veriyi kullanır
    assert g["kusursuz tahmin"] == pytest.approx(g["tahmin (1 gün önce)"])
    assert g["kusursuz tahmin"] != pytest.approx(g["kalıcılık"])
