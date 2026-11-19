"""Isolation Forest tabanlı anomali ve arıza tespiti.

Kaynak: Koçyiğit vd., 2025 (SIMPaCT - Operational ML for park-scale irrigation).
Parametreler:
- 200 karar ağacı (n_estimators=200)
- Bulaşma oranı: contamination = 0.05
- Pencere arıza eşiği: Pencerenin > %30'u anomali olarak etiketlenirse arıza kararı.
"""

from typing import Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


class IsolationForestQC:
    """Mevsimsel farkı alınmış toprak nemi ve sıcaklık serisinde Isolation Forest anomali filtresi."""

    def __init__(
        self,
        n_estimators: int = 200,
        contamination: float = 0.05,
        window_failure_threshold: float = 0.30,
        random_state: int = 42,
    ):
        self.n_estimators = n_estimators
        self.contamination = contamination
        self.threshold = window_failure_threshold
        self.random_state = random_state
        self.model = IsolationForest(
            n_estimators=self.n_estimators,
            contamination=self.contamination,
            random_state=self.random_state,
        )

    def detect_anomalies(
        self,
        series: pd.Series,
        lag: int = 24,
    ) -> Tuple[pd.Series, bool, float]:
        """Serideki anomalileri tespit eder ve arıza kararını döner.

        Parametreler:
            series: Sensör zaman serisi (örn. soil_raw, soil_vwc veya temp_c).
            lag: Mevsimsel/günlük fark alma gecikmesi (saatlik veri için 24).

        Döndürür:
            (anomaly_mask_series, is_fault, anomaly_ratio)
        """
        s = pd.to_numeric(series, errors="coerce").ffill().bfill()
        if len(s) < max(50, lag + 10):
            # Yetersiz veri durumunda güvenli pas geç
            return pd.Series(False, index=series.index), False, 0.0

        # Özellik matrisi: Değer, türev/fark ve gecikmeli fark
        diff1 = s.diff().fillna(0.0).values
        diff_lag = s.diff(lag).fillna(0.0).values
        x_mat = np.column_stack([s.values, diff1, diff_lag])

        preds = self.model.fit_predict(x_mat)
        is_anomaly = preds == -1  # -1 anomali, 1 normal

        anomaly_series = pd.Series(is_anomaly, index=series.index)
        ratio = float(np.mean(is_anomaly))
        is_fault = ratio >= self.threshold

        return anomaly_series, is_fault, ratio
