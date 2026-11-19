"""Mevsimsel ARIMA (SARIMA) tabanlı toprak nemi ve hava parametresi tahmincisi."""

from typing import Any, Optional, Tuple, Union

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX


class SarimaBaselineForecaster:
    """Mevsimsel ARIMA (SARIMA) referans tahmin modeli."""

    def __init__(
        self,
        order: Tuple[int, int, int] = (1, 1, 1),
        seasonal_order: Tuple[int, int, int, int] = (1, 0, 0, 24),
        forecast_horizon: int = 24,
    ):
        self.order = order
        self.seasonal_order = seasonal_order
        self.forecast_horizon = forecast_horizon
        self.fitted_model: Optional[Any] = None

    def fit_predict(
        self,
        series: Union[pd.Series, np.ndarray],
        horizon: Optional[int] = None,
    ) -> np.ndarray:
        """Seriye SARIMA modeli uydurup belirtilen ufukta tahmin döndürür."""
        h = horizon or self.forecast_horizon
        vals = pd.to_numeric(series, errors="coerce").dropna().values
        if len(vals) < 48:
            # Yetersiz seride son değer yedeği
            last_val = float(vals[-1]) if len(vals) > 0 else 0.25
            return np.full(h, last_val)

        try:
            model = SARIMAX(
                vals[-240:],  # Son 10 günün verisiyle fit
                order=self.order,
                seasonal_order=self.seasonal_order,
                enforce_stationarity=False,
                enforce_invertibility=False,
            )
            res = model.fit(disp=False)
            preds = res.forecast(steps=h)
            return np.array(preds)
        except Exception:
            # Yakınsamama durumunda lineer trend / persistence fallback
            last_val = float(vals[-1])
            return np.full(h, last_val)
