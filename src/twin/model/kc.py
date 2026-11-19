"""Bitki katsayısı (Kc) hesaplama modülü.

Yöntemler:
1. Aşama / takvim bazlı tablo lookup (FAO-56 Tablo 12 & WUCOLS).
2. NDVI tabanlı dinamik Kc: Kc = NDVI^2 (Obriejetan & Krexner 2024, Viyana çalışması; status: assumption).
"""

from typing import Optional, Union

import numpy as np
import pandas as pd

from twin.config import DEFAULT_CONFIG, CropParameters


def get_stage_based_kc(
    month: int,
    veg_type: str = "lawn",
    crop_params: Optional[CropParameters] = None,
) -> float:
    """Aylık mevsime bağlı aşama bazlı bitki katsayısını (Kc) döndürür.

    Kaynak: FAO-56 Tablo 12 ve WUCOLS (Serin iklim çimi / park örtüsü).
    Doğrulama durumu: to_verify.
    """
    params = crop_params or DEFAULT_CONFIG.crop

    # İstanbul için tipik sulama dönemi fenolojik evreleri:
    # Nisan-Mayıs: Başlangıç (ini)
    # Haziran-Ağustos: Orta sezon (mid)
    # Eylül-Ekim: Sezon sonu (end)
    if month in (4, 5):
        return float(params.kc_initial.value)
    elif month in (6, 7, 8):
        return float(params.kc_mid.value)
    elif month in (9, 10):
        return float(params.kc_end.value)
    else:
        # Kış ve erken ilkbahar düşük transpirasyon
        return float(params.kc_winter.value)


def get_ndvi_based_kc(
    ndvi: Union[float, np.ndarray, pd.Series],
    exponent: Optional[float] = None,
    kc_min: Optional[float] = None,
    kc_max: Optional[float] = None,
    crop_params: Optional[CropParameters] = None,
) -> Union[float, np.ndarray, pd.Series]:
    """Sentinel-2 NDVI değerinden bitki katsayısını (Kc) tahmin eder.

    Formül: Kc = clamp(NDVI^exponent, kc_min, kc_max)
    Kaynak: Obriejetan & Krexner (2024), Urban Climate 58:102192 (Viyana çalışması).
    Doğrulama durumu: assumption (Türkiye koşulları için kalibre edilecek).
    """
    params = crop_params or DEFAULT_CONFIG.crop
    exp_val = exponent if exponent is not None else float(params.kc_ndvi_exponent.value)
    min_val = kc_min if kc_min is not None else float(params.kc_ndvi_min.value)
    max_val = kc_max if kc_max is not None else float(params.kc_ndvi_max.value)

    clipped_ndvi = np.clip(ndvi, 0.0, 1.0)
    kc = np.power(clipped_ndvi, exp_val)
    if isinstance(kc, (pd.Series, np.ndarray)):
        return np.clip(kc, min_val, max_val)
    return min(max_val, max(min_val, float(kc)))
