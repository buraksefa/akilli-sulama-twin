"""Kayan pencereli k-En Yakın Komşu (kNN) toprak nemi tahmincisi.

24-72 saatlik toprak nemi (VWC / depletion) tahmin ufku.
Pencere boyutu: 200 - 900 saatlik geçmiş gözlem dizileri.
"""

from typing import Optional, Union

import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors


class RollingKNNForecaster:
    """Kayan pencereli kNN ile çok adımlı toprak nemi yörünge tahmincisi."""

    def __init__(
        self,
        history_window: int = 48,  # Örüntü eşleme için kullanılan geçmiş adım
        forecast_horizon: int = 24,  # İleriye doğru tahmin ufku
        n_neighbors: int = 5,
        max_train_size: int = 500,  # 200-900 saatlik eğitim hafızası
    ):
        self.history_window = history_window
        self.forecast_horizon = forecast_horizon
        self.n_neighbors = n_neighbors
        self.max_train_size = max_train_size
        self.nn_model = NearestNeighbors(n_neighbors=self.n_neighbors, metric="euclidean")
        self.x_patterns: Optional[np.ndarray] = None
        self.y_targets: Optional[np.ndarray] = None

    def fit(self, series: Union[pd.Series, np.ndarray]) -> "RollingKNNForecaster":
        """Zaman serisinden (history_window -> forecast_horizon) örüntü çiftlerini çıkarır."""
        vals = pd.to_numeric(series, errors="coerce").dropna().values
        if len(vals) > self.max_train_size:
            vals = vals[-self.max_train_size :]

        total_window = self.history_window + self.forecast_horizon
        if len(vals) < total_window + self.n_neighbors:
            # Yetersiz veri durumunda son değeri sakla
            self.x_patterns = None
            self.y_targets = None
            return self

        x_list = []
        y_list = []
        for i in range(len(vals) - total_window + 1):
            x_pat = vals[i : i + self.history_window]
            y_pat = vals[i + self.history_window : i + total_window]
            x_list.append(x_pat)
            y_list.append(y_pat)

        self.x_patterns = np.array(x_list)
        self.y_targets = np.array(y_list)
        self.nn_model.fit(self.x_patterns)
        return self

    def predict(self, recent_history: Union[pd.Series, np.ndarray]) -> np.ndarray:
        """Son history_window uzunluğundaki gözlemden ileriye dönük horizon tahminini üretir."""
        vals = pd.to_numeric(recent_history, errors="coerce").dropna().values
        if len(vals) < self.history_window or self.x_patterns is None or self.y_targets is None:
            # Fallback: Son değeri ufuk boyunca tekrarla (persistence)
            last_val = float(vals[-1]) if len(vals) > 0 else 0.25
            return np.full(self.forecast_horizon, last_val)

        query = vals[-self.history_window :].reshape(1, -1)
        distances, indices = self.nn_model.kneighbors(query)

        # En yakın komşuların yörüngelerinin ağırlıklı ortalaması
        weights = 1.0 / (distances[0] + 1e-5)
        weights /= np.sum(weights)

        matched_targets = self.y_targets[indices[0]]  # (k, horizon)
        forecast = np.average(matched_targets, axis=0, weights=weights)
        return forecast
