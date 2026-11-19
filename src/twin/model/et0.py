"""Referans Evapotranspirasyon (ETo) hesaplama modülü.

Uygulanan yöntemler:
1. FAO-56 Günlük Penman-Monteith (FAO Irrigation and Drainage Paper No. 56, Denklem 6)
2. FAO-56 Saatlik Penman-Monteith (FAO-56, Denklem 53)
3. Hargreaves-Samani Yöntemi (FAO-56, Denklem 52)

Tüm değişkenlerin birimleri ve kaynak denklem numaraları docstring içerisinde belirtilmiştir.
"""

import math
from typing import Optional, Union

import numpy as np
import pandas as pd

# Güneş sabiti Gsc [MJ / (m2 * min)] - FAO-56 Denklem 21
SOLAR_CONSTANT_GSC = 0.0820

# Stefan-Boltzmann sabiti sigma [MJ / (K4 * m2 * gun)] - FAO-56 Denklem 39
STEFAN_BOLTZMANN_DAILY = 4.903e-9

# Referans çim albedo katsayısı alpha [-] - FAO-56 Denklem 38
CANOPY_ALBEDO = 0.23


def atmospheric_pressure(elevation_m: float = 30.0) -> float:
    """Rakıma bağlı standart atmosferik basıncı (P) hesaplar [kPa].

    Kaynak: FAO-56 Denklem 7.
    Birim: kPa.
    """
    return 101.3 * ((293.0 - 0.0065 * elevation_m) / 293.0) ** 5.26


def psychrometric_constant(pressure_kpa: float) -> float:
    """Psikrometrik sabiti (gamma) hesaplar [kPa / °C].

    Kaynak: FAO-56 Denklem 8.
    Birim: kPa / °C.
    """
    return 0.000665 * pressure_kpa


def saturation_vapour_pressure(temp_c: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
    """Verilen sıcaklıkta doymuş buhar basıncını e°(T) hesaplar [kPa].

    Kaynak: FAO-56 Denklem 11.
    Birim: kPa.
    """
    return 0.6108 * np.exp((17.27 * temp_c) / (temp_c + 237.3))


def slope_vapour_pressure_curve(temp_c: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
    """Doymuş buhar basıncı eğrisinin eğimini (Delta) hesaplar [kPa / °C].

    Kaynak: FAO-56 Denklem 13.
    Birim: kPa / °C.
    """
    es = saturation_vapour_pressure(temp_c)
    return (4098.0 * es) / ((temp_c + 237.3) ** 2)


def extraterrestrial_radiation_daily(
    day_of_year: Union[int, np.ndarray],
    latitude_deg: float = 41.04,
) -> Union[float, np.ndarray]:
    """Günlük atmosfer dışı güneş radyasyonunu (Ra) hesaplar [MJ / (m2 * gün)].

    Kaynak: FAO-56 Denklem 21, 23, 24, 25.
    Birim: MJ / (m2 * gün).
    """
    phi = math.radians(latitude_deg)
    # Ters göreli Dünya-Güneş mesafesi (dr) - Denklem 23
    dr = 1.0 + 0.033 * np.cos((2.0 * np.pi / 365.0) * day_of_year)
    # Güneş sapması (delta) - Denklem 24
    delta = 0.409 * np.sin((2.0 * np.pi / 365.0) * day_of_year - 1.39)
    # Gün batımı saat açısı (omega_s) - Denklem 25
    x = -np.tan(phi) * np.tan(delta)
    x = np.clip(x, -1.0, 1.0)
    omega_s = np.arccos(x)

    # Ra formülü - Denklem 21
    ra = (
        (24.0 * 60.0 / np.pi)
        * SOLAR_CONSTANT_GSC
        * dr
        * (omega_s * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(omega_s))
    )
    return ra


def clear_sky_radiation(
    ra_mj_m2_day: Union[float, np.ndarray],
    elevation_m: float = 30.0,
) -> Union[float, np.ndarray]:
    """Açık gökyüzü güneş radyasyonunu (Rso) hesaplar [MJ / (m2 * gün)].

    Kaynak: FAO-56 Denklem 37.
    Birim: MJ / (m2 * gün).
    """
    return (0.75 + 2.0e-5 * elevation_m) * ra_mj_m2_day


def net_radiation_daily(
    rs_mj_m2_day: Union[float, np.ndarray],
    rso_mj_m2_day: Union[float, np.ndarray],
    ea_kpa: Union[float, np.ndarray],
    tmax_c: Union[float, np.ndarray],
    tmin_c: Union[float, np.ndarray],
) -> Union[float, np.ndarray]:
    """Günlük net radyasyonu (Rn) hesaplar [MJ / (m2 * gün)].

    Kaynak: FAO-56 Denklem 38, 39, 40.
    Birim: MJ / (m2 * gün).
    """
    # Net kısa dalga radyasyonu (Rns) - Denklem 38
    rns = (1.0 - CANOPY_ALBEDO) * rs_mj_m2_day

    # Bağıl güneşlenme oranı sınırlaması (0.3 <= Rs/Rso <= 1.0)
    rel_solar = np.clip(rs_mj_m2_day / np.maximum(rso_mj_m2_day, 1e-4), 0.3, 1.0)

    # Net uzun dalga radyasyonu (Rnl) - Denklem 39
    tmax_k4 = (tmax_c + 273.16) ** 4
    tmin_k4 = (tmin_c + 273.16) ** 4
    rnl = (
        STEFAN_BOLTZMANN_DAILY
        * ((tmax_k4 + tmin_k4) / 2.0)
        * (0.34 - 0.14 * np.sqrt(np.maximum(ea_kpa, 0.0)))
        * (1.35 * rel_solar - 0.35)
    )

    # Net radyasyon Rn = Rns - Rnl - Denklem 40
    return rns - rnl


def fao56_penman_monteith_daily(
    temp_mean_c: Union[float, np.ndarray, pd.Series],
    temp_max_c: Union[float, np.ndarray, pd.Series],
    temp_min_c: Union[float, np.ndarray, pd.Series],
    wind_speed_2m_ms: Union[float, np.ndarray, pd.Series],
    rad_mj_m2_day: Union[float, np.ndarray, pd.Series],
    rh_mean_pct: Optional[Union[float, np.ndarray, pd.Series]] = None,
    rh_max_pct: Optional[Union[float, np.ndarray, pd.Series]] = None,
    rh_min_pct: Optional[Union[float, np.ndarray, pd.Series]] = None,
    dewpoint_c: Optional[Union[float, np.ndarray, pd.Series]] = None,
    day_of_year: Optional[Union[int, np.ndarray, pd.Series]] = None,
    latitude_deg: float = 41.04,
    elevation_m: float = 30.0,
) -> Union[float, np.ndarray, pd.Series]:
    """FAO-56 Günlük Penman-Monteith referans evapotranspirasyonu (ETo) hesaplar [mm / gün].

    Kaynak: FAO-56 Denklem 6.
    Denklem:
        ETo = (0.408 * Delta * (Rn - G) + gamma * (900 / (T + 273)) * u2 * (es - ea)) /
              (Delta + gamma * (1 + 0.34 * u2))

    Parametreler:
        temp_mean_c: Günlük ortalama sıcaklık [°C]
        temp_max_c: Günlük en yüksek sıcaklık [°C]
        temp_min_c: Günlük en düşük sıcaklık [°C]
        wind_speed_2m_ms: 2 metre yükseklikte ortalama rüzgâr hızı [m/s]
        rad_mj_m2_day: Günlük güneş radyasyonu [MJ / (m2 * gün)]
        rh_mean_pct: Günlük ortalama bağıl nem [%]
        rh_max_pct, rh_min_pct: Günlük azami ve asgari bağıl nem [%]
        dewpoint_c: Ortalama çiy noktası sıcaklığı [°C]
        day_of_year: Yılın günü (1-366)
        latitude_deg: Enlem [ondalık derece]
        elevation_m: Rakım [metre]

    Döndürür:
        ETo [mm / gün].
    """
    pressure = atmospheric_pressure(elevation_m)
    gamma = psychrometric_constant(pressure)
    delta = slope_vapour_pressure_curve(temp_mean_c)

    # es = (e°(Tmax) + e°(Tmin)) / 2 - Denklem 12
    e_tmax = saturation_vapour_pressure(temp_max_c)
    e_tmin = saturation_vapour_pressure(temp_min_c)
    es = (e_tmax + e_tmin) / 2.0

    # ea hesabı
    if rh_max_pct is not None and rh_min_pct is not None:
        # Denklem 17
        ea = (e_tmin * (rh_max_pct / 100.0) + e_tmax * (rh_min_pct / 100.0)) / 2.0
    elif rh_mean_pct is not None:
        # Denklem 19
        ea = (rh_mean_pct / 100.0) * es
    elif dewpoint_c is not None:
        # Denklem 14
        ea = saturation_vapour_pressure(dewpoint_c)
    else:
        # Çiy noktası veya nem yoksa Tmin varsayımı (FAO-56 s. 58)
        ea = saturation_vapour_pressure(temp_min_c)

    # Ra ve Rso hesabı
    doy = day_of_year if day_of_year is not None else 180
    ra = extraterrestrial_radiation_daily(doy, latitude_deg)
    rso = clear_sky_radiation(ra, elevation_m)

    # Net radyasyon Rn (Günlük toprak ısı akısı G ≈ 0 - Denklem 42)
    rn = net_radiation_daily(rad_mj_m2_day, rso, ea, temp_max_c, temp_min_c)
    g = 0.0

    # FAO-56 Denklem 6
    numerator = 0.408 * delta * (rn - g) + gamma * (900.0 / (temp_mean_c + 273.0)) * wind_speed_2m_ms * (
        es - ea
    )
    denominator = delta + gamma * (1.0 + 0.34 * wind_speed_2m_ms)

    eto = numerator / denominator
    if isinstance(eto, (pd.Series, np.ndarray)):
        return np.maximum(eto, 0.0)
    return max(0.0, float(eto))


def fao56_penman_monteith_hourly(
    temp_c: Union[float, np.ndarray, pd.Series],
    rh_pct: Union[float, np.ndarray, pd.Series],
    wind_speed_2m_ms: Union[float, np.ndarray, pd.Series],
    rad_mj_m2_h: Union[float, np.ndarray, pd.Series],
    day_of_year: int = 180,
    hour_of_day: int = 12,
    latitude_deg: float = 41.04,
    elevation_m: float = 30.0,
) -> Union[float, np.ndarray, pd.Series]:
    """FAO-56 Saatlik Penman-Monteith referans evapotranspirasyonu hesaplar [mm / saat].

    UYARI / DURUM: Bu fonksiyon DENEYSEL olarak işaretlenmiştir ve tez simülasyonlarında
    DOĞRUDAN KULLANILMAMAKTADIR (kök bölgesi su dengesi simülasyonlarında FAO-56 Bölüm 8
    ve SIMPaCT gereği günlük Penman-Monteith adımı olan `fao56_penman_monteith_daily` esastır).
    Gece net radyasyonu basitleştirilmiş Rn = -0.05 MJ/(m2*saat) kabulü taşır (status: assumption).

    Kaynak: FAO-56 Denklem 53.
    Denklem:
        ETo = (0.408 * Delta * (Rn - G) + gamma * (37 / (T + 273)) * u2 * (es - ea)) /
              (Delta + gamma * (1 + 0.34 * u2))

    Birim: mm / saat.
    """
    pressure = atmospheric_pressure(elevation_m)
    gamma = psychrometric_constant(pressure)
    delta = slope_vapour_pressure_curve(temp_c)

    es = saturation_vapour_pressure(temp_c)
    ea = es * (rh_pct / 100.0)

    # Saatlik basitleştirilmiş net radyasyon Rn
    # Gündüz Rn ≈ 0.77 * Rs; Gece Rn ≈ -0.2 * Rso_hr
    is_day = rad_mj_m2_h > 0.01
    rn = np.where(is_day, (1.0 - CANOPY_ALBEDO) * rad_mj_m2_h, -0.05)

    # Toprak ısı akısı G: Gündüz G = 0.1 * Rn, Gece G = 0.5 * Rn (FAO-56 Denklem 45, 46)
    g = np.where(is_day, 0.1 * rn, 0.5 * rn)

    numerator = 0.408 * delta * (rn - g) + gamma * (37.0 / (temp_c + 273.0)) * wind_speed_2m_ms * (es - ea)
    denominator = delta + gamma * (1.0 + 0.34 * wind_speed_2m_ms)

    eto = numerator / denominator
    if isinstance(eto, (pd.Series, np.ndarray)):
        return np.maximum(eto, 0.0)
    return max(0.0, float(eto))


def hargreaves_samani_daily(
    temp_mean_c: Union[float, np.ndarray, pd.Series],
    temp_max_c: Union[float, np.ndarray, pd.Series],
    temp_min_c: Union[float, np.ndarray, pd.Series],
    day_of_year: Union[int, np.ndarray, pd.Series],
    latitude_deg: float = 41.04,
) -> Union[float, np.ndarray, pd.Series]:
    """Hargreaves-Samani sıcaklık tabanlı günlük referans evapotranspirasyon hesabı [mm / gün].

    Kaynak: FAO-56 Denklem 52.
    Denklem:
        ETo = 0.0023 * (Tmean + 17.8) * (Tmax - Tmin)^0.5 * Ra * 0.408
    Birim: mm / gün.
    """
    ra = extraterrestrial_radiation_daily(day_of_year, latitude_deg)
    # Ra [MJ/(m2*gun)]'yi mm/gun eşdeğerine çevirmek için 0.408 ile çarpılır
    tdiff = np.maximum(temp_max_c - temp_min_c, 0.0)
    eto = 0.0023 * (temp_mean_c + 17.8) * np.sqrt(tdiff) * (0.408 * ra)
    if isinstance(eto, (pd.Series, np.ndarray)):
        return np.maximum(eto, 0.0)
    return max(0.0, float(eto))
