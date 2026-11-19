"""Kök bölgesi toprak su dengesi modeli (FAO-56 Bölüm 8).

Kaynaklar:
- FAO Irrigation and Drainage Paper 56, Bölüm 8 (Denklemler 81-88):
  * TAW = 1000 * (theta_fc - theta_wp) * Zr                  [mm] (Denklem 82)
  * RAW = p * TAW                                             [mm] (Denklem 83)
  * Ks  = (TAW - Dr) / ((1 - p) * TAW)   Dr > RAW ise, aksi halde 1.0 (Denklem 84)
  * ETc = Kc * ETo                                            [mm]
  * ETa = Ks * Kc * ETo                                       [mm] (Denklem 81)
  * Dr,i = Dr,i-1 - (P - RO) - I_eff - CR + ETa + DP          [mm] (Denklem 85)
  * DP = max(0, - (Dr,i-1 - (P - RO) - I_eff + ETa))          [mm] (Denklem 88)
"""

from dataclasses import dataclass
from typing import Optional, Union

import numpy as np
import pandas as pd

from twin.config import TwinConfig


@dataclass
class WaterBalanceState:
    """Kök bölgesi su dengesi anlık durum değişkenleri."""

    depletion_mm: float  # Dr [mm] (Kök bölgesi su açığı / tükenmesi)
    theta_vwc: float  # theta [m3/m3] (Hacimsel su içeriği)
    ks: float  # Ks [-] (Su stres katsayısı, 0.0 - 1.0)
    eta_mm: float  # ETa [mm] (Gerçek evapotranspirasyon)
    dp_mm: float  # DP [mm] (Derin sızma)
    ro_mm: float  # RO [mm] (Yüzey akışı)


def compute_taw(theta_fc: float, theta_wp: float, root_depth_m: float) -> float:
    """Toplam Kullanılabilir Su miktarını (TAW) hesaplar [mm].

    Kaynak: FAO-56 Denklem 82: TAW = 1000 * (theta_fc - theta_wp) * Zr
    Birim: mm.
    """
    return 1000.0 * (theta_fc - theta_wp) * root_depth_m


def compute_raw(taw_mm: float, p_depletion: float) -> float:
    """Kolaylıkla Kullanılabilir Su miktarını (RAW) hesaplar [mm].

    Kaynak: FAO-56 Denklem 83: RAW = p * TAW
    Birim: mm.
    """
    return p_depletion * taw_mm


def compute_ks(dr_mm: float, taw_mm: float, raw_mm: float, p_depletion: float) -> float:
    """Su stres katsayısını (Ks) hesaplar [-].

    Kaynak: FAO-56 Denklem 84:
        Ks = (TAW - Dr) / ((1 - p) * TAW)   (Dr > RAW ise)
        Ks = 1.0                             (Dr <= RAW ise)
    Birim: Boyutsuz [0.0 - 1.0].
    """
    if dr_mm <= raw_mm:
        return 1.0
    denom = (1.0 - p_depletion) * taw_mm
    if denom <= 1e-6:
        return 0.0
    ks = (taw_mm - dr_mm) / denom
    return float(np.clip(ks, 0.0, 1.0))


def depletion_to_vwc(dr_mm: float, theta_fc: float, root_depth_m: float) -> float:
    """Tükenme miktarından (Dr) hacimsel su içeriğini (theta) hesaplar [m3/m3].

    Gözlem operatörü: theta = theta_fc - Dr / (1000 * Zr)
    Birim: m3/m3.
    """
    return theta_fc - (dr_mm / (1000.0 * root_depth_m))


def vwc_to_depletion(theta_vwc: float, theta_fc: float, root_depth_m: float) -> float:
    """Hacimsel su içeriğinden (theta) kök bölgesi tükenmesini (Dr) hesaplar [mm].

    Ters operatör: Dr = 1000 * Zr * (theta_fc - theta)
    Birim: mm.
    """
    return 1000.0 * root_depth_m * (theta_fc - theta_vwc)


def simulate_water_balance_step(
    dr_prev_mm: float,
    eto_mm: float,
    kc: float,
    precip_mm: float,
    irrigation_mm: float,
    theta_fc: float = 0.28,
    theta_wp: float = 0.14,
    root_depth_m: float = 0.30,
    p_depletion: float = 0.50,
    irr_efficiency: float = 0.75,
    runoff_thresh_mm: float = 25.0,
    capillary_rise_mm: float = 0.0,
) -> WaterBalanceState:
    """Tek bir zaman adımı (gün veya saat) için FAO-56 Bölüm 8 su dengesini çözer.

    Parametreler:
        dr_prev_mm: Önceki adımın tükenmesi Dr,t-1 [mm]
        eto_mm: Referans evapotranspirasyon ETo [mm]
        kc: Bitki katsayısı Kc [-]
        precip_mm: Toplam yağış P [mm]
        irrigation_mm: Uygulanan brüt sulama I [mm]
        theta_fc: Tarla kapasitesi [m3/m3]
        theta_wp: Solma noktası [m3/m3]
        root_depth_m: Kök derinliği Zr [m]
        p_depletion: Kritik tükenme kesri p [-]
        irr_efficiency: Sulama verimi eta_irr [-]
        runoff_thresh_mm: Yüzey akışı eşiği [mm]
        capillary_rise_mm: Kılcal yükselme CR [mm]

    Döndürür:
        WaterBalanceState nesnesi.
    """
    taw = compute_taw(theta_fc, theta_wp, root_depth_m)
    raw = compute_raw(taw, p_depletion)

    # Su stresi katsayısı (Ks) - Denklem 84
    ks = compute_ks(dr_prev_mm, taw, raw, p_depletion)

    # Gerçek evapotranspirasyon (ETa) - Denklem 81
    etc = kc * eto_mm
    eta = ks * etc

    # Yüzey akışı (RO) ve etkili sulama (I_eff)
    ro = max(0.0, precip_mm - runoff_thresh_mm) if precip_mm > runoff_thresh_mm else 0.0
    p_net = precip_mm - ro
    i_eff = irrigation_mm * irr_efficiency

    # Geçici tükenme (Dr_temp)
    dr_temp = dr_prev_mm - p_net - i_eff - capillary_rise_mm + eta

    # Derin sızma (DP) - Tarla kapasitesi aşıldığında (Dr < 0) - Denklem 88
    if dr_temp < 0.0:
        dp = -dr_temp
        dr = 0.0
    else:
        dp = 0.0
        dr = min(taw, dr_temp)  # TAW'dan fazla kuruyamaz (solma noktasında sınırlanır)

    theta = depletion_to_vwc(dr, theta_fc, root_depth_m)

    return WaterBalanceState(
        depletion_mm=dr,
        theta_vwc=theta,
        ks=ks,
        eta_mm=eta,
        dp_mm=dp,
        ro_mm=ro,
    )


def run_water_balance_simulation(
    df_weather: pd.DataFrame,
    kc_series: Union[float, pd.Series],
    irrigation_series: Optional[Union[float, pd.Series]] = None,
    initial_dr_mm: float = 0.0,
    config: Optional[TwinConfig] = None,
) -> pd.DataFrame:
    """Tüm zaman serisi boyunca vektörel/adımlı FAO-56 su dengesini simüle eder.

    Girdi df_weather sütunları:
    - 'eto_mm': Referans evapotranspirasyon (hesaplanmışsa) veya hesaplanır
    - 'rain_mm': Yağış (mm)

    Döndürür:
        Simülasyon çıktılarını içeren pandas.DataFrame.
    """
    cfg = config or TwinConfig()
    theta_fc = float(cfg.soil.theta_fc.value)
    theta_wp = float(cfg.soil.theta_wp.value)
    root_depth_m = float(cfg.soil.root_depth_m.value)
    p_depletion = float(cfg.soil.p_depletion.value)
    runoff_thresh = float(cfg.soil.runoff_threshold_mm.value)
    irr_eff = float(cfg.irrigation.efficiency.value)

    taw = compute_taw(theta_fc, theta_wp, root_depth_m)
    raw = compute_raw(taw, p_depletion)

    n = len(df_weather)
    dates = df_weather.index

    eto_arr = df_weather["eto_mm"].values if "eto_mm" in df_weather.columns else np.zeros(n)
    rain_arr = df_weather["rain_mm"].values if "rain_mm" in df_weather.columns else np.zeros(n)

    if isinstance(kc_series, pd.Series):
        kc_arr = kc_series.values
    elif isinstance(kc_series, (int, float)):
        kc_arr = np.full(n, float(kc_series))
    else:
        kc_arr = np.array(kc_series)

    if irrigation_series is None:
        irr_arr = np.zeros(n)
    elif isinstance(irrigation_series, pd.Series):
        irr_arr = irrigation_series.values
    elif isinstance(irrigation_series, (int, float)):
        irr_arr = np.full(n, float(irrigation_series))
    else:
        irr_arr = np.array(irrigation_series)

    dr_arr = np.zeros(n)
    theta_arr = np.zeros(n)
    ks_arr = np.zeros(n)
    eta_arr = np.zeros(n)
    dp_arr = np.zeros(n)
    ro_arr = np.zeros(n)

    dr_curr = initial_dr_mm

    for i in range(n):
        state = simulate_water_balance_step(
            dr_prev_mm=dr_curr,
            eto_mm=eto_arr[i],
            kc=kc_arr[i],
            precip_mm=rain_arr[i],
            irrigation_mm=irr_arr[i],
            theta_fc=theta_fc,
            theta_wp=theta_wp,
            root_depth_m=root_depth_m,
            p_depletion=p_depletion,
            irr_efficiency=irr_eff,
            runoff_thresh_mm=runoff_thresh,
        )
        dr_arr[i] = state.depletion_mm
        theta_arr[i] = state.theta_vwc
        ks_arr[i] = state.ks
        eta_arr[i] = state.eta_mm
        dp_arr[i] = state.dp_mm
        ro_arr[i] = state.ro_mm
        dr_curr = state.depletion_mm

    out_df = pd.DataFrame(
        {
            "eto_mm": eto_arr,
            "kc": kc_arr,
            "etc_mm": kc_arr * eto_arr,
            "rain_mm": rain_arr,
            "irrigation_gross_mm": irr_arr,
            "irrigation_net_mm": irr_arr * irr_eff,
            "eta_mm": eta_arr,
            "ks": ks_arr,
            "depletion_mm": dr_arr,
            "theta_vwc": theta_arr,
            "dp_mm": dp_arr,
            "ro_mm": ro_arr,
            "taw_mm": taw,
            "raw_mm": raw,
        },
        index=dates,
    )
    return out_df
