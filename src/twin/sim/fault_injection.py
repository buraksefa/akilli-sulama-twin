"""Sensör arıza enjeksiyonu ve belirsizlik simülasyonu (RQ1 Deneyleri).

Arıza türleri:
1. Sabit Yanlılık (Bias): Ölçümlere sabit delta ekleme (+/- 0.05 m3/m3)
2. Kayma (Drift): Zamanla artan doğrusal sapma (delta * t)
3. Donma (Freeze / Flatline): Sensörün belirli bir değerde takılı kalması
4. Kopma / Eksik Değer (Dropout): Rastgele veya blok halinde veri kaybı (NaN)
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class FaultConfig:
    """Arıza enjeksiyon parametreleri."""

    fault_type: str  # 'none', 'bias', 'drift', 'freeze', 'dropout', 'combined'
    bias_value: float = 0.05  # m3/m3
    drift_rate_per_day: float = 0.001  # m3/m3/gün
    freeze_start_day: int = 30
    freeze_duration_days: int = 15
    freeze_value: float = 0.26  # Sabit nem
    dropout_prob: float = 0.20  # Rastgele eksik olasılığı


def inject_sensor_faults(
    theta_series: pd.Series,
    config: FaultConfig,
    seed: int = 42,
) -> pd.Series:
    """Temiz sensör nem serisine belirtilen arıza senaryosunu enjekte eder."""
    if config.fault_type == "none":
        return theta_series.copy()

    rng = np.random.default_rng(seed)
    s = theta_series.copy().values.astype(float)
    n = len(s)

    if config.fault_type in ("bias", "combined"):
        s += config.bias_value

    if config.fault_type in ("drift", "combined"):
        drift = np.linspace(0, config.drift_rate_per_day * (n / 24.0), n)
        s += drift

    if config.fault_type in ("freeze", "combined"):
        start_idx = config.freeze_start_day * 24 if len(theta_series) > 365 else config.freeze_start_day
        duration_idx = (
            config.freeze_duration_days * 24 if len(theta_series) > 365 else config.freeze_duration_days
        )
        end_idx = min(n, start_idx + duration_idx)
        if start_idx < n:
            s[start_idx:end_idx] = config.freeze_value

    if config.fault_type in ("dropout", "combined"):
        mask = rng.random(n) < config.dropout_prob
        s[mask] = np.nan

    # Fiziksel sınırları koru
    s = np.where(np.isnan(s), np.nan, np.clip(s, 0.0, 0.60))
    return pd.Series(s, index=theta_series.index)
