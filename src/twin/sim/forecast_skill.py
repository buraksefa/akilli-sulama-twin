"""Hava tahmini isabeti ve tahmine dayalı sulama kararının değeri.

1. İsabet: Open-Meteo önceki-koşu tahminleri (k gün önceden) ERA5-Land günlük değerleriyle karşılaştırılır.
   Referans ERA5'tir (gözlem değil, reanaliz; ETo'su bu projede FAO-56 PM ile hesaplandı). Open-Meteo ETo'su
   kendi modelinin FAO-56 hesabıdır; fark yöntem ve ızgara farkını da içerir.
   Taban: kalıcılık (bugünkü ETo = dünkü ETo; yağış = dünkü yağış).
2. Kararın değeri: sanal dünyada ikizler üç bilgi düzeyiyle karar verir: kalıcılık, gerçek tahmin, kusursuz
   tahmin (ERA5'in kendisi). Dünya her durumda ERA5 ile yürür.
"""

from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd

from twin.config import TwinConfig
from twin.sim.virtual_world import World, run_world, summarize_run


def _daily_naive(df: pd.DataFrame) -> pd.DataFrame:
    """Dizini saat dilimsiz günlük tarihe çevirir (ERA5 UTC'li, Open-Meteo UTC günleri dilimsiz gelir)."""
    out = df.copy()
    idx = pd.DatetimeIndex(out.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    out.index = idx.normalize()
    out.attrs = dict(df.attrs)
    return out


def _cont(fc: pd.Series, ref: pd.Series) -> Dict[str, float]:
    m = fc.notna() & ref.notna()
    e = fc[m] - ref[m]
    return {
        "n": int(m.sum()),
        "bias_mm": float(e.mean()),
        "mae_mm": float(e.abs().mean()),
        "rmse_mm": float(np.sqrt((e**2).mean())),
        "r": float(np.corrcoef(fc[m], ref[m])[0, 1]) if m.sum() > 2 else np.nan,
        "toplam_tahmin_mm": float(fc[m].sum()),
        "toplam_ref_mm": float(ref[m].sum()),
    }


def _events(fc: pd.Series, ref: pd.Series, thr: float) -> Dict[str, float]:
    m = fc.notna() & ref.notna()
    f, o = fc[m] >= thr, ref[m] >= thr
    hits, misses, fa = int((f & o).sum()), int((~f & o).sum()), int((f & ~o).sum())
    return {
        f"pod_{thr:g}mm": hits / (hits + misses) if hits + misses else np.nan,
        f"far_{thr:g}mm": fa / (hits + fa) if hits + fa else np.nan,
        f"csi_{thr:g}mm": hits / (hits + misses + fa) if hits + misses + fa else np.nan,
        f"gozlenen_gun_{thr:g}mm": int(o.sum()),
    }


def skill_table(
    forecasts: pd.DataFrame,
    reference: pd.DataFrame,
    leads: Iterable[int] = range(1, 8),
    rain_thresholds: Iterable[float] = (1.0, 5.0),
) -> pd.DataFrame:
    """Her vade ve kalıcılık tabanı için ETo ve yağış isabet ölçütleri."""
    forecasts, reference = _daily_naive(forecasts), _daily_naive(reference)
    ref = reference.reindex(forecasts.index)
    rows = []
    candidates = [(f"{k} gün önce", forecasts[f"eto_d{k}"], forecasts[f"rain_d{k}"]) for k in leads]
    candidates.append(("kalıcılık (dün)", ref["eto_mm"].shift(1), ref["rain_mm"].shift(1)))
    for name, eto_fc, rain_fc in candidates:
        row = {"tahmin": name}
        row.update({f"eto_{k}": v for k, v in _cont(eto_fc, ref["eto_mm"]).items()})
        row.update({f"yagis_{k}": v for k, v in _cont(rain_fc, ref["rain_mm"]).items()})
        for thr in rain_thresholds:
            row.update(_events(rain_fc, ref["rain_mm"], thr))
        rows.append(row)
    return pd.DataFrame(rows)


def decision_value(
    world: World,
    weather: pd.DataFrame,
    forecasts: pd.DataFrame,
    lead: int = 1,
    strategies: Iterable[str] = ("MODEL", "SENSOR", "ENKF"),
    seeds: Iterable[int] = range(10),
    margin: float = 0.9,
    config: Optional[TwinConfig] = None,
) -> pd.DataFrame:
    """Aynı sanal dünyada ikizlerin üç bilgi düzeyindeki sonuçları (tohum başına satır)."""
    weather, forecasts = _daily_naive(weather), _daily_naive(forecasts)
    fc = pd.DataFrame({"eto_fc": forecasts[f"eto_d{lead}"], "rain_fc": forecasts[f"rain_d{lead}"]}).reindex(
        weather.index
    )
    perfect = pd.DataFrame({"eto_fc": weather["eto_mm"], "rain_fc": weather["rain_mm"]})
    levels = {"kalıcılık": None, f"tahmin ({lead} gün önce)": fc.dropna(), "kusursuz tahmin": perfect}
    rows = []
    for strat in strategies:
        for level, f in levels.items():
            for seed in seeds:
                r = run_world(
                    world, weather, strat, margin=margin, sensor_seed=seed, config=config, forecast=f
                )
                rows.append(
                    {"strateji": strat, "bilgi": level, "tohum": seed, **summarize_run(r), "kaynak": r.source}
                )
    return pd.DataFrame(rows)
