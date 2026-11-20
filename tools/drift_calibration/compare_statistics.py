"""Kayma testi kalibrasyonu, adım 2: aday istatistikleri karşılaştırır.

Eşik 2020-2021 sağlam sensörlerinden (sezon içi en büyük |istatistik|, %99 ve %100 dilim), değerlendirme 2022-2024.
Çıktı: outputs/sensor_qc_drift/statistic_comparison.csv. Kaynak: synthetic_world+era5.
"""

import glob
import pickle

import numpy as np
import pandas as pd

S = []
for f in sorted(glob.glob("outputs/sensor_qc_drift/calib/series_*.pkl")):
    S += pickle.load(open(f, "rb"))


def stat_series(s, kind, win=60, minp=45):
    r = s["r"]
    T = len(r)
    t = np.arange(T, dtype=float)
    cet = np.cumsum(s["kc"] * s["eto"]) / (1000 * s["zr"])
    rn = np.minimum(s["rain"], 999)
    cin = np.cumsum(rn + s["dose"]) / (1000 * s["zr"])
    out = np.full(T, np.nan)
    for d in range(T):
        m = np.isfinite(r[: d + 1])
        idx = np.flatnonzero(m)
        idx = idx[idx > d - win]
        if len(idx) < minp:
            continue
        y = r[idx]
        tt = t[idx]
        if kind == "ols":
            X = np.c_[np.ones(len(idx)), tt]
        elif kind == "ols_et":
            X = np.c_[np.ones(len(idx)), tt, cet[idx]]
        elif kind == "ols_et_in":
            X = np.c_[np.ones(len(idx)), tt, cet[idx], cin[idx]]
        elif kind == "ts":
            i, j = np.triu_indices(len(idx), k=15)
            out[d] = np.median((y[j] - y[i]) / (tt[j] - tt[i]))
            continue
        X = X - np.r_[0, X[:, 1:].mean(0)]
        b = np.linalg.lstsq(X, y, rcond=None)[0]
        out[d] = b[1]
    return out


res = []
for kind, win in [("ols", 60), ("ols", 90), ("ts", 60), ("ols_et", 60), ("ols_et", 90), ("ols_et_in", 90)]:
    rows = []
    for s in S:
        st = stat_series(s, kind, win, min(45, int(win * 0.75)))
        rows.append(
            dict(
                year=s["year"],
                fault=s["fault"],
                mx=np.nanmax(np.abs(st)) if np.isfinite(st).any() else 0,
                st=st,
            )
        )
    df = pd.DataFrame(rows)
    cal = df[(df.year <= 2021) & (df.fault == "none")].mx
    for qq in (0.99, 1.0):
        thr = cal.quantile(qq)
        ev = df[df.year >= 2022]
        fa = (ev[ev.fault == "none"].mx > thr).mean()
        dr = ev[ev.fault == "drift"]
        det = (dr.mx > thr).mean()
        days = [np.flatnonzero(np.abs(np.nan_to_num(x)) > thr)[0] for x, m in zip(dr.st, dr.mx) if m > thr]
        res.append(
            dict(
                stat=kind,
                win=win,
                q=qq,
                thr=round(thr, 5),
                false_alarm_eval=round(fa, 4),
                drift_det_eval=round(det, 3),
                delay_med=np.median(days) if days else np.nan,
                delay_p90=np.percentile(days, 90) if days else np.nan,
                freeze_flag=round((ev[ev.fault == "freeze"].mx > thr).mean(), 3),
            )
        )
    print(pd.DataFrame(res).tail(2).to_string(index=False), flush=True)
pd.DataFrame(res).to_csv("outputs/sensor_qc_drift/statistic_comparison.csv", index=False)
