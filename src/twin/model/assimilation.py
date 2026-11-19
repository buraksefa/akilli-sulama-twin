"""Veri asimilasyonu modülü (Nudging ve Topluluk Kalman Filtresi - EnKF).

Model-sensör entegrasyonu:
- Gözlem operatörü: theta = theta_fc - Dr / (1000 * Zr)
- Sensör hata modeli: theta_obs = a * theta_true + b + eps,  eps ~ N(0, sigma^2)
- Tahminciler:
  1. Yalnızca model (su dengesi simülasyonu)
  2. Yalnızca sensör (doğrudan ölçüm dönüşümü)
  3. Asimile edilmiş ikiz (Doğrudan Nudging ve EnKF)
"""

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from twin.model.waterbalance import (
    compute_taw,
    depletion_to_vwc,
    simulate_water_balance_step,
    vwc_to_depletion,
)


@dataclass
class SensorCalibrationErrorModel:
    """Düşük maliyetli toprak nemi sensörü kalibrasyon ve gürültü modeli.

    theta_obs = slope * theta_true + bias + noise
    """

    slope: float = 1.0  # a katsayısı
    bias: float = 0.0  # b yanlılık (bias) [m3/m3]
    noise_std: float = 0.02  # sigma ölçüm standart sapması [m3/m3]

    def observe(self, theta_true: float, rng: Optional[np.random.Generator] = None) -> float:
        """Gerçek nem değerinden gürültülü ve yanlı sensör ölçümü üretir."""
        gen = rng or np.random.default_rng()
        noise = gen.normal(0, self.noise_std)
        theta_obs = self.slope * theta_true + self.bias + noise
        return float(np.clip(theta_obs, 0.0, 0.60))

    def invert(self, theta_obs: float) -> float:
        """Sensör ölçümünü bilinen kalibrasyon parametreleriyle düzeltir."""
        if abs(self.slope) < 1e-4:
            return theta_obs
        theta_corr = (theta_obs - self.bias) / self.slope
        return float(np.clip(theta_corr, 0.0, 0.60))


class DirectNudgingAssimilation:
    """Basit Doğrudan Nudging (Luenberger gözlemcisi) asimilasyon tahmincisi.

    Dr,asimil = Dr,model + K_nudge * (Dr,obs - Dr,model)
    """

    def __init__(self, nudge_factor: float = 0.30):
        self.nudge_factor = float(np.clip(nudge_factor, 0.0, 1.0))

    def update(
        self,
        dr_model: float,
        theta_obs: Optional[float],
        theta_fc: float = 0.28,
        root_depth_m: float = 0.30,
    ) -> float:
        """Ölçüm varsa nudging güncellemesi yapar, yoksa model tükenmesini döner."""
        if theta_obs is None or np.isnan(theta_obs):
            return dr_model

        dr_obs = vwc_to_depletion(theta_obs, theta_fc, root_depth_m)
        taw = 1000.0 * theta_fc * root_depth_m  # Max limit
        dr_assimilated = dr_model + self.nudge_factor * (dr_obs - dr_model)
        return float(np.clip(dr_assimilated, 0.0, taw))


class EnsembleKalmanFilter:
    """Kök bölgesi toprak su dengesi için Topluluk Kalman Filtresi (EnKF).

    Durum vektörü: x = [Dr] (Kök bölgesi tükenmesi, mm).
    Gözlem: y = theta_obs [m3/m3].
    Gözlem operatörü: h(Dr) = theta_fc - Dr / (1000 * Zr).
    """

    def __init__(
        self,
        num_members: int = 50,
        theta_fc: float = 0.28,
        theta_wp: float = 0.14,
        root_depth_m: float = 0.30,
        p_depletion: float = 0.50,
        obs_error_std: float = 0.02,
        proc_error_std_dr: float = 0.80,  # mm
        seed: int = 42,
    ):
        self.n_members = num_members
        self.theta_fc = theta_fc
        self.theta_wp = theta_wp
        self.root_depth_m = root_depth_m
        self.p_depletion = p_depletion
        self.obs_std = obs_error_std
        self.proc_std = proc_error_std_dr
        self.taw = compute_taw(theta_fc, theta_wp, root_depth_m)
        self.rng = np.random.default_rng(seed)

        # Başlangıç topluluğunu tarla kapasitesi civarında başlat
        self.ensemble_dr = np.clip(self.rng.normal(2.0, 1.0, num_members), 0.0, self.taw)

    def forecast_step(
        self,
        eto_mm: float,
        kc: float,
        precip_mm: float,
        irrigation_mm: float,
        irr_efficiency: float = 0.75,
    ) -> np.ndarray:
        """Model fiziğiyle her topluluk üyesini bir adım ileri yürütür ve süreç gürültüsü ekler."""
        new_dr = np.zeros(self.n_members)
        for i in range(self.n_members):
            # Forcing perturbasyonu (ör. ETo ve yağış belirsizliği)
            eto_pert = max(0.0, eto_mm + self.rng.normal(0, 0.15 * max(eto_mm, 0.5)))
            p_pert = max(0.0, precip_mm + (self.rng.normal(0, 0.2 * precip_mm) if precip_mm > 0 else 0.0))

            state = simulate_water_balance_step(
                dr_prev_mm=self.ensemble_dr[i],
                eto_mm=eto_pert,
                kc=kc,
                precip_mm=p_pert,
                irrigation_mm=irrigation_mm,
                theta_fc=self.theta_fc,
                theta_wp=self.theta_wp,
                root_depth_m=self.root_depth_m,
                p_depletion=self.p_depletion,
                irr_efficiency=irr_efficiency,
            )
            # Süreç gürültüsü
            dr_noisy = state.depletion_mm + self.rng.normal(0, self.proc_std)
            new_dr[i] = np.clip(dr_noisy, 0.0, self.taw)

        self.ensemble_dr = new_dr
        return self.ensemble_dr

    def analysis_step(self, theta_obs: Optional[float]) -> Tuple[float, float, float]:
        """Sensör ölçümü geldiğinde EnKF güncellemesini uygular.

        Döndürür:
            (dr_mean, dr_std, theta_mean)
        """
        if theta_obs is None or np.isnan(theta_obs):
            # Ölçüm yoksa yalnızca tahmin durumunu raporla
            dr_mean = float(np.mean(self.ensemble_dr))
            dr_std = float(np.std(self.ensemble_dr))
            theta_mean = depletion_to_vwc(dr_mean, self.theta_fc, self.root_depth_m)
            return dr_mean, dr_std, theta_mean

        # Gözlem operatörü h(x)
        h_ensemble = np.array(
            [depletion_to_vwc(dr, self.theta_fc, self.root_depth_m) for dr in self.ensemble_dr]
        )
        h_mean = np.mean(h_ensemble)
        x_mean = np.mean(self.ensemble_dr)

        # Kovaryanslar
        x_anom = self.ensemble_dr - x_mean
        h_anom = h_ensemble - h_mean

        # P_xy = Cov(x, h(x)), P_yy = Var(h(x)) + R
        p_xy = np.dot(x_anom, h_anom) / (self.n_members - 1)
        p_yy = np.dot(h_anom, h_anom) / (self.n_members - 1) + (self.obs_std**2)

        # Kalman Kazancı K = P_xy / P_yy
        k_gain = p_xy / (p_yy + 1e-8)

        # Sentetik ölçüm topluluğu (perturbed observations)
        y_perturbed = theta_obs + self.rng.normal(0, self.obs_std, self.n_members)

        # Durum güncellemesi
        innovation = y_perturbed - h_ensemble
        self.ensemble_dr = np.clip(self.ensemble_dr + k_gain * innovation, 0.0, self.taw)

        dr_mean = float(np.mean(self.ensemble_dr))
        dr_std = float(np.std(self.ensemble_dr))
        theta_mean = depletion_to_vwc(dr_mean, self.theta_fc, self.root_depth_m)
        return dr_mean, dr_std, theta_mean
