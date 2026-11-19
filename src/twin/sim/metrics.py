"""Simülasyon performans ve doğrulama metrikleri.

Hesaplanan metrikler:
- Su tüketimi: Toplam derinlik (mm), Toplam hacim (m3)
- Bitki stresi: Stresli gün sayısı (Ks < 1.0), Kümülatif stres şiddeti (sum(1 - Ks))
- Operasyonel: Sulama olayı sayısı, Ortalama sulama dozu
- Model doğrulama: RMSE, Yanlılık (Bias), KGE (Kling-Gupta Efficiency), NSE (Nash-Sutcliffe Efficiency)
"""

from dataclasses import dataclass
from typing import Dict, Union

import numpy as np
import pandas as pd


@dataclass
class SimulationMetrics:
    """Strateji simülasyonu özet metrikleri."""

    strategy_name: str
    total_water_mm: float  # Toplam uygulanan brüt sulama [mm]
    total_water_m3: float  # Park sulanan alanı bazında toplam su [m3]
    stress_days_count: int  # Ks < 1.0 olan gün sayısı
    cumulative_stress: float  # sum(1.0 - Ks)
    irrigation_events_count: int  # Sulama yapılan gün/olay sayısı
    mean_event_dose_mm: float  # Olay başına ortalama sulama dozu [mm]
    deep_percolation_mm: float  # Toplam derin sızma kaybı [mm]
    mean_ks: float  # Sezonluk ortalama Ks

    def to_dict(self) -> Dict[str, Union[str, float, int]]:
        return {
            "strategy": self.strategy_name,
            "total_water_mm": round(self.total_water_mm, 2),
            "total_water_m3": round(self.total_water_m3, 2),
            "stress_days": self.stress_days_count,
            "cumulative_stress": round(self.cumulative_stress, 2),
            "irrigation_events": self.irrigation_events_count,
            "mean_dose_mm": round(self.mean_event_dose_mm, 2),
            "deep_percolation_mm": round(self.deep_percolation_mm, 2),
            "mean_ks": round(self.mean_ks, 3),
        }


def calculate_simulation_metrics(
    sim_df: pd.DataFrame,
    strategy_name: str,
    irrigated_area_m2: float = 100000.0,
) -> SimulationMetrics:
    """Simülasyon çıktı DataFrame'inden temel performans metriklerini hesaplar."""
    irr_gross = sim_df["irrigation_gross_mm"].values
    ks = sim_df["ks"].values
    dp = sim_df["dp_mm"].values if "dp_mm" in sim_df.columns else np.zeros(len(sim_df))

    total_water_mm = float(np.sum(irr_gross))
    total_water_m3 = (total_water_mm / 1000.0) * irrigated_area_m2

    stress_mask = ks < 0.999
    stress_days = int(np.sum(stress_mask))
    cum_stress = float(np.sum(np.maximum(0.0, 1.0 - ks)))

    events = int(np.sum(irr_gross > 0.1))
    mean_dose = float(total_water_mm / events) if events > 0 else 0.0

    return SimulationMetrics(
        strategy_name=strategy_name,
        total_water_mm=total_water_mm,
        total_water_m3=total_water_m3,
        stress_days_count=stress_days,
        cumulative_stress=cum_stress,
        irrigation_events_count=events,
        mean_event_dose_mm=mean_dose,
        deep_percolation_mm=float(np.sum(dp)),
        mean_ks=float(np.mean(ks)),
    )


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Kök Ortalama Kare Hata (RMSE)."""
    mask = ~np.isnan(y_true) & ~np.isnan(y_pred)
    if np.sum(mask) == 0:
        return 0.0
    return float(np.sqrt(np.mean((y_true[mask] - y_pred[mask]) ** 2)))


def mean_bias_error(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Ortalama Yanlılık Hatası (Bias = mean(y_pred - y_true))."""
    mask = ~np.isnan(y_true) & ~np.isnan(y_pred)
    if np.sum(mask) == 0:
        return 0.0
    return float(np.mean(y_pred[mask] - y_true[mask]))


def nash_sutcliffe_efficiency(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Nash-Sutcliffe Verimlilik Katsayısı (NSE).

    Kaynak: Nash & Sutcliffe (1970).
    NSE = 1 - (sum((y_true - y_pred)^2) / sum((y_true - mean(y_true))^2))
    """
    mask = ~np.isnan(y_true) & ~np.isnan(y_pred)
    yt = y_true[mask]
    yp = y_pred[mask]
    if len(yt) < 2:
        return 1.0
    denom = np.sum((yt - np.mean(yt)) ** 2)
    if denom <= 1e-8:
        return 1.0 if np.allclose(yt, yp) else 0.0
    return float(1.0 - (np.sum((yt - yp) ** 2) / denom))


def kling_gupta_efficiency(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Kling-Gupta Verimlilik Katsayısı (KGE).

    Kaynak: Gupta vd. (2009).
    KGE = 1 - sqrt((r - 1)^2 + (alpha - 1)^2 + (beta - 1)^2)
    burada r = korelasyon, alpha = std(pred)/std(true), beta = mean(pred)/mean(true).
    """
    mask = ~np.isnan(y_true) & ~np.isnan(y_pred)
    yt = y_true[mask]
    yp = y_pred[mask]
    if len(yt) < 2:
        return 1.0

    std_t = np.std(yt)
    std_p = np.std(yp)
    mean_t = np.mean(yt)
    mean_p = np.mean(yp)

    if std_t <= 1e-8 or std_p <= 1e-8 or abs(mean_t) <= 1e-8:
        return float(1.0 - (rmse(yt, yp) / (abs(mean_t) + 1e-4)))

    r = float(np.corrcoef(yt, yp)[0, 1])
    alpha = std_p / std_t
    beta = mean_p / mean_t

    kge_val = 1.0 - np.sqrt((r - 1.0) ** 2 + (alpha - 1.0) ** 2 + (beta - 1.0) ** 2)
    return float(kge_val)
