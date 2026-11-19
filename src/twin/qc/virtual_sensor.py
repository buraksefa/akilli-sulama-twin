"""Sanal sensör (Virtual Sensor) ve arıza yedekleme modelleri.

Yöntemler:
1. Çoklu sensör durumu: Kraskov-Stögbauer-Grassberger (KSG) karşılıklı bilgi (Mutual Information)
   ile en iyi komşu seçimi + Küçük MLP (1 gizli katman, 10 ReLU nöronu).
2. Tek sensör yedeği: ERA5 meteoroloji ve FAO-56 kök bölgesi su dengesi modelinden türetilmiş sanal sensör.

Kaynak: Koçyiğit vd., 2025 (SIMPaCT) & Kraskov, Stögbauer, Grassberger (2004).
"""

from typing import Optional, Tuple, Union

import numpy as np
import pandas as pd
from sklearn.feature_selection import mutual_info_regression
from sklearn.neural_network import MLPRegressor

from twin.model.waterbalance import run_water_balance_simulation


class SpatialMLPVirtualSensor:
    """Çok sensörlü ağlarda komşu sensörlerden yapay sinir ağıyla kestirim yapan sanal sensör."""

    def __init__(
        self,
        hidden_layer_sizes: Tuple[int, ...] = (10,),
        max_iter: int = 500,
        random_state: int = 42,
    ):
        self.mlp = MLPRegressor(
            hidden_layer_sizes=hidden_layer_sizes,
            activation="relu",
            solver="adam",
            max_iter=max_iter,
            random_state=random_state,
        )
        self.best_neighbor_col: Optional[str] = None
        self.is_fitted = False

    def select_best_neighbor(
        self,
        target_series: pd.Series,
        neighbor_df: pd.DataFrame,
    ) -> str:
        """KSG tabanlı karşılıklı bilgi (Mutual Information) ile en yüksek ilişkili komşuyu seçer."""
        clean_df = neighbor_df.copy()
        clean_df["target"] = target_series
        clean_df = clean_df.dropna()

        x = clean_df.drop(columns=["target"])
        y = clean_df["target"]

        # KSG karşılıklı bilgi skoru
        mi_scores = mutual_info_regression(x, y, random_state=42)
        best_idx = int(np.argmax(mi_scores))
        self.best_neighbor_col = str(x.columns[best_idx])
        return self.best_neighbor_col

    def fit(self, target_series: pd.Series, neighbor_series: pd.Series) -> "SpatialMLPVirtualSensor":
        """Tek gizli katmanlı (10 ReLU) MLP modelini eğitir."""
        df = pd.DataFrame({"y": target_series, "x": neighbor_series}).dropna()
        if len(df) > 10:
            x_mat = df[["x"]].values
            y_vec = df["y"].values
            self.mlp.fit(x_mat, y_vec)
            self.is_fitted = True
        return self

    def predict(self, neighbor_series: pd.Series) -> pd.Series:
        """Komşu sensör değerlerinden hedef sensör değerini tahmin eder."""
        if not self.is_fitted:
            return neighbor_series.copy()
        x_mat = neighbor_series.ffill().bfill().values.reshape(-1, 1)
        preds = self.mlp.predict(x_mat)
        return pd.Series(preds, index=neighbor_series.index)


class PhysicalModelVirtualSensor:
    """Tek sensörlü veya tüm sensörlerin koptuğu durumda ERA5 + Su Dengesi tabanlı sanal sensör."""

    def __init__(self, theta_fc: float = 0.28, theta_wp: float = 0.14, root_depth_m: float = 0.30):
        self.theta_fc = theta_fc
        self.theta_wp = theta_wp
        self.root_depth_m = root_depth_m

    def estimate_vwc(
        self,
        weather_df: pd.DataFrame,
        kc_series: Union[float, pd.Series] = 0.85,
        irrigation_series: Optional[Union[float, pd.Series]] = None,
    ) -> pd.Series:
        """Meteoroloji ve uygulanan sulama verisinden fiziksel su dengesiyle toprak nemini (VWC) üretir."""
        sim_df = run_water_balance_simulation(
            df_weather=weather_df,
            kc_series=kc_series,
            irrigation_series=irrigation_series,
        )
        return sim_df["theta_vwc"]
