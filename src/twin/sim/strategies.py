"""Sulama karar stratejileri (S0 - S4).

Stratejiler:
- S0: Sabit Takvim (Fixed Schedule) - Belirli günlerde sabit doz uygulama
- S1: Sensör Eşiği (Sensor Threshold) - Sensör ölçümü kritik eşiğin altına düşünce
- S2: Yalnız ET Tabanlı (ET-Only) - Sensörsüz, model su açığı RAW'a ulaşınca
- S3: Tahminli Sulama (Forecast-Guided) - Yağış tahmini eşiği aşarsa erteleme
- S4: Asimile Edilmiş İkiz (Assimilated Twin) - EnKF forecast_step + analysis_step ile karar
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional

import numpy as np
import pandas as pd

from twin.config import TwinConfig
from twin.model.assimilation import DirectNudgingAssimilation, EnsembleKalmanFilter
from twin.model.waterbalance import compute_raw, compute_taw, depletion_to_vwc, vwc_to_depletion


class IrrigationStrategy(ABC):
    """Tüm sulama stratejileri için temel soyut sınıf."""

    name: str = "BaseStrategy"

    @abstractmethod
    def decide(
        self,
        day_idx: int,
        current_date: pd.Timestamp,
        weather_row: pd.Series,
        state_depletion_mm: float,
        sensor_theta_obs: Optional[float],
        forecast_rain_24h_mm: float,
        config: TwinConfig,
    ) -> float:
        """Belirtilen gün için uygulanacak brüt sulama miktarını [mm] döndürür."""
        pass


class S0FixedSchedule(IrrigationStrategy):
    """S0: Sabit Takvim Stratejisi.

    Belirtilen gün aralığında sabit doz sulama uygular (varsayılanlar config.py'den alınır).
    """

    def __init__(self, interval_days: Optional[int] = None, dose_mm: Optional[float] = None):
        self.name = "S0_FixedSchedule"
        self.interval = interval_days
        self.dose = dose_mm

    def decide(
        self,
        day_idx: int,
        current_date: pd.Timestamp,
        weather_row: pd.Series,
        state_depletion_mm: float,
        sensor_theta_obs: Optional[float],
        forecast_rain_24h_mm: float,
        config: TwinConfig,
    ) -> float:
        interval = (
            self.interval if self.interval is not None else int(config.irrigation.s0_interval_days.value)
        )
        dose = self.dose if self.dose is not None else float(config.irrigation.s0_dose_mm.value)
        if day_idx % interval == 0:
            return dose
        return 0.0


class S1SensorThreshold(IrrigationStrategy):
    """S1: Sensör Eşiği Stratejisi.

    Sensörden okunan hacimsel su içeriği kritik eşiğin altına indiğinde
    tarla kapasitesine kadar su uygular.
    """

    def __init__(self, target_fill_fraction: float = 1.0):
        self.name = "S1_SensorThreshold"
        self.fill_frac = target_fill_fraction

    def decide(
        self,
        day_idx: int,
        current_date: pd.Timestamp,
        weather_row: pd.Series,
        state_depletion_mm: float,
        sensor_theta_obs: Optional[float],
        forecast_rain_24h_mm: float,
        config: TwinConfig,
    ) -> float:
        theta_fc = float(config.soil.theta_fc.value)
        theta_wp = float(config.soil.theta_wp.value)
        zr = float(config.soil.root_depth_m.value)
        p = float(config.soil.p_depletion.value)
        eff = float(config.irrigation.efficiency.value)

        taw = compute_taw(theta_fc, theta_wp, zr)
        raw = compute_raw(taw, p)
        critical_theta = theta_fc - (raw / (1000.0 * zr))

        # Sensör okuması varsa onu kullan, yoksa model durumuna dön
        if sensor_theta_obs is not None and not np.isnan(sensor_theta_obs):
            curr_theta = sensor_theta_obs
            dr_sensor = vwc_to_depletion(curr_theta, theta_fc, zr)
        else:
            curr_theta = depletion_to_vwc(state_depletion_mm, theta_fc, zr)
            dr_sensor = state_depletion_mm

        if curr_theta <= critical_theta or dr_sensor >= raw:
            net_need = max(0.0, dr_sensor * self.fill_frac)
            gross_dose = net_need / eff
            return float(min(gross_dose, 35.0))
        return 0.0


class S2ETOnly(IrrigationStrategy):
    """S2: Yalnız ET Tabanlı Strateji (Sensörsüz).

    Su dengesi modelinin hesapladığı kümülatif tükenme Dr >= RAW olduğunda sulama yapar.
    """

    def __init__(self, target_fill_fraction: float = 1.0):
        self.name = "S2_ETOnly"
        self.fill_frac = target_fill_fraction

    def decide(
        self,
        day_idx: int,
        current_date: pd.Timestamp,
        weather_row: pd.Series,
        state_depletion_mm: float,
        sensor_theta_obs: Optional[float],
        forecast_rain_24h_mm: float,
        config: TwinConfig,
    ) -> float:
        theta_fc = float(config.soil.theta_fc.value)
        theta_wp = float(config.soil.theta_wp.value)
        zr = float(config.soil.root_depth_m.value)
        p = float(config.soil.p_depletion.value)
        eff = float(config.irrigation.efficiency.value)

        taw = compute_taw(theta_fc, theta_wp, zr)
        raw = compute_raw(taw, p)

        if state_depletion_mm >= raw:
            gross_dose = (state_depletion_mm * self.fill_frac) / eff
            return float(min(gross_dose, 35.0))
        return 0.0


class S3ForecastGuided(IrrigationStrategy):
    """S3: Tahminli Sulama Stratejisi.

    Tükenme RAW'a ulaşsa bile, önümüzdeki 24-48 saatte beklenen yağış
    yağış eşiğini (örn. 5 mm) aşıyorsa sulamayı atlar / erteler.
    """

    def __init__(self, rain_threshold_mm: float = 5.0, target_fill_fraction: float = 1.0):
        self.name = "S3_ForecastGuided"
        self.rain_thresh = rain_threshold_mm
        self.fill_frac = target_fill_fraction

    def decide(
        self,
        day_idx: int,
        current_date: pd.Timestamp,
        weather_row: pd.Series,
        state_depletion_mm: float,
        sensor_theta_obs: Optional[float],
        forecast_rain_24h_mm: float,
        config: TwinConfig,
    ) -> float:
        theta_fc = float(config.soil.theta_fc.value)
        theta_wp = float(config.soil.theta_wp.value)
        zr = float(config.soil.root_depth_m.value)
        p = float(config.soil.p_depletion.value)
        eff = float(config.irrigation.efficiency.value)

        taw = compute_taw(theta_fc, theta_wp, zr)
        raw = compute_raw(taw, p)

        if state_depletion_mm >= raw:
            if forecast_rain_24h_mm >= self.rain_thresh:
                return 0.0
            gross_dose = (state_depletion_mm * self.fill_frac) / eff
            return float(min(gross_dose, 35.0))
        return 0.0


class S4AssimilatedTwin(IrrigationStrategy):
    """S4: Asimile Edilmiş Dijital İkiz Stratejisi.

    Fiziksel su dengesi ve sensör gözlemlerini EnKF (forecast_step + analysis_step)
    veya Direct Nudging ile asimile ederek en doğru durum kestirimini üretir.
    """

    def __init__(self, use_enkf: bool = True, target_fill_fraction: float = 1.0):
        self.name = "S4_AssimilatedTwin"
        self.use_enkf = use_enkf
        self.fill_frac = target_fill_fraction
        self.enkf: Optional[EnsembleKalmanFilter] = None
        self.nudging = DirectNudgingAssimilation()
        self.last_irr_gross_mm = 0.0

    def decide(
        self,
        day_idx: int,
        current_date: pd.Timestamp,
        weather_row: pd.Series,
        state_depletion_mm: float,
        sensor_theta_obs: Optional[float],
        forecast_rain_24h_mm: float,
        config: TwinConfig,
    ) -> float:
        theta_fc = float(config.soil.theta_fc.value)
        theta_wp = float(config.soil.theta_wp.value)
        zr = float(config.soil.root_depth_m.value)
        p = float(config.soil.p_depletion.value)
        eff = float(config.irrigation.efficiency.value)
        obs_std = float(config.assimilation.obs_error_std.value)
        proc_std = float(config.assimilation.proc_error_std_dr.value)

        taw = compute_taw(theta_fc, theta_wp, zr)
        raw = compute_raw(taw, p)

        eto = float(weather_row.get("eto_mm", 4.0))
        kc = float(weather_row.get("kc", 0.85))
        rain = float(weather_row.get("rain_mm", 0.0))

        if self.use_enkf:
            if self.enkf is None:
                self.enkf = EnsembleKalmanFilter(
                    num_members=40,
                    theta_fc=theta_fc,
                    theta_wp=theta_wp,
                    root_depth_m=zr,
                    p_depletion=p,
                    obs_error_std=obs_std,
                    proc_error_std_dr=proc_std,
                )

            # 1. Adım: EnKF her gün model fiziği ile durum tahminini (forecast step) yürütür
            self.enkf.forecast_step(
                eto_mm=eto,
                kc=kc,
                precip_mm=rain,
                irrigation_mm=self.last_irr_gross_mm,
                irr_efficiency=eff,
            )

            # 2. Adım: Sensör ölçümüyle Kalman analizi (analysis step)
            dr_est, _, _ = self.enkf.analysis_step(sensor_theta_obs)
        else:
            dr_est = self.nudging.update(state_depletion_mm, sensor_theta_obs, theta_fc, zr)

        if dr_est >= raw:
            gross_dose = (dr_est * self.fill_frac) / eff
            gross_dose = float(min(gross_dose, 35.0))
            self.last_irr_gross_mm = gross_dose
            return gross_dose

        self.last_irr_gross_mm = 0.0
        return 0.0


def get_all_strategies() -> Dict[str, IrrigationStrategy]:
    """Tüm 5 stratejiyi (S0 - S4) içeren sözlüğü döndürür."""
    return {
        "S0": S0FixedSchedule(),
        "S1": S1SensorThreshold(),
        "S2": S2ETOnly(),
        "S3": S3ForecastGuided(rain_threshold_mm=5.0),
        "S4": S4AssimilatedTwin(use_enkf=True),
    }
