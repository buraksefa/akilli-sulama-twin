"""ARIMA 24 saatlik kalıntı testi tabanlı arıza tespiti.

Kaynak: Koçyiğit vd., 2025 (SIMPaCT).
Kural: 24 adımlık ARIMA tahmininde |gerçek - tahmin| > 2 * sigma eşiği
noktaların %30'undan fazlasında aşılırsa sensör arızalı kabul edilir.
"""

from typing import Tuple

import numpy as np
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA


class ArimaResidualQC:
    """ARIMA kalıntıları üzerinden sensör güvenilirlik kontrolü."""

    def __init__(
        self,
        order: Tuple[int, int, int] = (1, 1, 1),
        forecast_horizon: int = 24,
        sigma_multiplier: float = 2.0,
        fault_ratio_threshold: float = 0.30,
    ):
        self.order = order
        self.horizon = forecast_horizon
        self.sigma_multiplier = sigma_multiplier
        self.threshold = fault_ratio_threshold

    def check_residuals(
        self,
        train_series: pd.Series,
        test_series: pd.Series,
    ) -> Tuple[pd.Series, bool, float]:
        """Eğitim serisine ARIMA uydurup test serisinde 2σ aşım oranını kontrol eder.

        Parametreler:
            train_series: Modelin eğitileceği geçmiş seri (örn. son 7 gün)
            test_series: Denetlenecek güncel seri (24 saat)

        Döndürür:
            (exceedance_mask, is_fault, exceedance_ratio)
        """
        y_train = pd.to_numeric(train_series, errors="coerce").dropna().values
        y_test = pd.to_numeric(test_series, errors="coerce").dropna().values

        if len(y_train) < 24 or len(y_test) == 0:
            return pd.Series(False, index=test_series.index), False, 0.0

        try:
            model = ARIMA(y_train, order=self.order)
            fitted = model.fit()
            # Eğitim kalıntı standart sapması (sigma)
            sigma = float(np.std(fitted.resid))
            if sigma < 1e-4:
                sigma = 1e-2

            forecast_res = fitted.forecast(steps=len(y_test))
            forecast_vals = np.array(forecast_res)

            residuals = np.abs(y_test - forecast_vals)
            threshold_val = self.sigma_multiplier * sigma
            exceeds = residuals > threshold_val

            ratio = float(np.mean(exceeds))
            is_fault = ratio >= self.threshold

            return pd.Series(exceeds, index=test_series.index[: len(exceeds)]), is_fault, ratio
        except Exception:
            # Sayısal yakınsama hatası durumunda basit kayan ortalama kalıntı yedeği
            mean_val = float(np.mean(y_train[-24:]))
            std_val = float(np.std(y_train[-24:])) or 1e-2
            exceeds = np.abs(y_test - mean_val) > (self.sigma_multiplier * std_val)
            ratio = float(np.mean(exceeds)) if len(exceeds) > 0 else 0.0
            return pd.Series(exceeds, index=test_series.index[: len(exceeds)]), ratio >= self.threshold, ratio
