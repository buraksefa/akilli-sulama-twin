"""Çevrimiçi sensör QC: kurallar, ikize bağlantı ve sağlam sensörde yanlış alarm olmaması."""

import numpy as np
import pandas as pd
import pytest

from twin.config import TwinConfig
from twin.qc.online import QC_REASONS, OnlineSensorQC
from twin.sim.heterogeneity import world_variant
from twin.sim.virtual_world import build_world, load_world_spec, run_world

SPEC = "data/scenarios/yildiz_dunya.json"
GEOJSON = "data/public/parks.geojson"
FC = 0.28


def _qc():
    return OnlineSensorQC(FC, TwinConfig().sensor_qc)


@pytest.mark.parametrize("seed", range(20))
def test_healthy_noisy_sensor_passes(seed):
    """Sağlam, gürültülü (σ 0,02) sensör 214 günlük sezonda hiç reddedilmez."""
    rng = np.random.default_rng(seed)
    q = _qc()
    reasons = [q.update(0.22 + rng.normal(0, 0.02))[1] for _ in range(214)]
    assert set(reasons) == {"ok"}


def test_frozen_value_rejected_after_window_and_released_after():
    q = _qc()
    out = [q.update(v)[1] for v in [0.20, 0.21, 0.19, 0.22]]
    out += [q.update(0.205)[1] for _ in range(8)]
    assert out[:4] == ["ok"] * 4
    assert "frozen" in out
    assert out.index("frozen") == 4 + 6  # 7 günlük pencerenin 7. günü
    assert q.update(0.25)[1] == "ok"  # değer yeniden değişince geri döner


def test_out_of_range_and_gap():
    q = _qc()
    assert q.update(0.75) == (None, "range")  # aralık dışı okuma eksik sayılır
    assert [q.update(float("nan"))[1] for _ in range(3)] == ["nodata", "nodata", "gap"]
    assert q.update(0.2)[1] == "ok"  # yeni okuma gelince kesinti biter


def test_missing_rate_rule():
    q = _qc()
    seq = [0.2, np.nan, 0.21, np.nan, np.nan, 0.22, np.nan, np.nan, 0.2, np.nan, 0.23]
    reasons = [q.update(v)[1] for v in seq]
    assert reasons[-1] == "missing"  # son 10 günde 6 eksik (> %50)
    assert reasons[0] == "ok"


def test_above_fc_latches():
    q = _qc()
    vals = [0.34, 0.35, 0.36]
    reasons = [q.update(v)[1] for v in vals]
    assert reasons == ["ok", "ok", "above_fc"]
    assert q.update(0.20)[1] == "above_fc"  # kalıcı


def test_saturation_check_excludes_in_one_day_only_when_saturated():
    q = _qc()
    assert q.update(0.34, saturated=False)[1] == "ok"
    assert _qc().update(0.34, saturated=True)[1] == "ok"  # pay 0,09 içinde
    q2 = _qc()
    assert q2.update(0.38, saturated=True)[1] == "saturation_check"
    assert q2.update(0.25)[1] == "saturation_check"
    assert set(QC_REASONS) >= {
        "ok",
        "nodata",
        "range",
        "gap",
        "missing",
        "frozen",
        "above_fc",
        "saturation_check",
    }


@pytest.fixture(scope="module")
def world():
    return build_world(world_variant(load_world_spec(SPEC), (2, 2), "random"), GEOJSON)


def _weather(n=90, seed=2):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-05-01", periods=n, freq="D")
    w = pd.DataFrame(
        {
            "eto_mm": rng.uniform(4, 7, n),
            "rain_mm": np.where(rng.random(n) < 0.15, rng.gamma(1.5, 8, n), 0.0),
        },
        index=idx,
    )
    w.attrs["source"] = "synthetic"
    return w


def test_qc_in_world_has_no_false_alarm_on_healthy_sensors(world):
    run = run_world(world, _weather(), "ENKF", qc=True)
    sd = run.sensors
    healthy = sd[sd["fault_type"] == "none"]
    assert healthy["qc_reason"].isin(["ok", "nodata"]).all()
    frozen = sd[(sd["fault_type"] == "freeze") & sd["fault_active"]]
    if len(frozen):
        assert (frozen["qc_reason"] == "frozen").any()
    assert run.qc is not None and len(run.qc) == len(world.sensors)


def test_qc_off_uses_every_reading(world):
    run = run_world(world, _weather(30), "SENSOR", qc=False)
    sd = run.sensors
    assert (sd["used"] == sd["theta_read"].notna()).all()
    assert run.qc is None


@pytest.mark.parametrize("seed", range(5))
def test_drift_rule_flags_linear_trend_against_model(seed):
    """Okuma = model + sabit sapma + 0,001/gün kayma + gürültü → kayma testi yakalar; sabit sapma yakalanmaz."""
    rng = np.random.default_rng(seed)
    model = 0.20 + 0.02 * np.sin(np.arange(150) / 9.0)
    q_drift, q_offset = _qc(), _qc()
    r_drift, r_offset = [], []
    for t, m in enumerate(model):
        noise = rng.normal(0, 0.02)
        r_drift.append(q_drift.update(m + 0.001 * t + noise, theta_model=m)[1])
        r_offset.append(q_offset.update(m + 0.03 + noise, theta_model=m)[1])
    assert "drift" in r_drift
    first = r_drift.index("drift")
    assert first >= int(TwinConfig().sensor_qc.drift_min_points.value) - 1
    assert set(r_drift[first:]) == {"drift"}  # kalıcı dışlama
    assert "drift" not in r_offset


def test_drift_rule_skipped_without_model_reference():
    q = _qc()
    reasons = [q.update(0.15 + 0.002 * t, theta_model=None)[1] for t in range(60)]
    assert "drift" not in reasons and np.isnan(q.drift_slope)


def test_world_drift_test_toggle(world):
    off = run_world(world, _weather(), "ENKF", qc=True, qc_drift=False).sensors
    assert not (off["qc_reason"] == "drift").any()
    assert {"theta_openloop", "drift_slope"} <= set(off.columns)
