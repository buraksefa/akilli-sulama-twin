"""SIMPaCT ile uyumlu kural tabanlı veri kalite filtreleri.

Kaynak: Koçyiğit, Javadi, Thomson, Pfautsch, Obst (2025). Operational machine learning
for park-scale irrigation to support urban cooling. arXiv:2508.11700 (Eşikler tam metinden doğrulandı).

Doğrulanmış SIMPaCT Kural ve Eşikleri:
1. Eksik Veri Oranı: Değerlendirme penceresinde eksik kayıt oranı > %50 ise arıza.
2. Boşluk (Gaps): Zaman serisinde 3 günü (> 72 saat / 259200 sn) aşan kesinti.
3. Donmuş Değer (120h Frozen / Flatline): 120 saatlik kayan pencerede mutlak değişim < %1 ise takılı sensör.
4. Sıçrama (Spike): 24 saatlik kayan medyana ve medyan mutlak sapmaya (MAD * 6.0) göre ani sıçramalar.
5. Fiziksel Aralık: DHT11 sıcaklık (0 - 50 °C), nem (%20 - 90), Toprak ham ADC (0 - 1023), VWC (0.0 - 0.60 m³/m³).
"""

from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

TIME_COLUMNS = ["pc_time_utc", "created_at", "time"]
ERR_BITS = {1: "dht", 2: "toprak", 4: "wifi", 8: "thingspeak", 16: "mqtt"}


def load_sensor_csv(path: Union[str, pd.DataFrame]) -> pd.DataFrame:
    """Sensör zaman serisi CSV dosyasını okur ve zaman indeksine göre sıralar."""
    if isinstance(path, pd.DataFrame):
        df = path.copy()
    else:
        df = pd.read_csv(path)

    tcol = next((c for c in TIME_COLUMNS if c in df.columns), None)
    if tcol is None:
        raise ValueError(f"Zaman sütunu bulunamadı (aranan sütunlar: {TIME_COLUMNS})")
    df["time"] = pd.to_datetime(df[tcol], utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    return df


def check_missing_rate(
    series: pd.Series,
    threshold: float = 0.50,
) -> Tuple[bool, float]:
    """SIMPaCT Kuralı 1: Penceredeki eksik (NaN) veri oranını kontrol eder.

    Kaynak: Koçyiğit vd. (2025).
    Eşik: Eksik oranı > %50 (threshold=0.50) ise seri/pencere geçersiz sayılır.

    Döndürür:
        (is_excessive_missing, missing_ratio)
    """
    total = len(series)
    if total == 0:
        return True, 1.0
    missing_count = int(series.isna().sum())
    ratio = float(missing_count / total)
    return ratio > threshold, ratio


def find_gaps(df: pd.DataFrame, interval_s: float = 60.0) -> pd.DataFrame:
    """Beklenen örnekleme aralığının 1.5 katını aşan kesinti aralıklarını tespit eder."""
    dt = df["time"].diff().dt.total_seconds()
    mask = dt > 1.5 * interval_s
    gaps = pd.DataFrame(
        {
            "start": df["time"].shift(1)[mask],
            "end": df["time"][mask],
            "seconds": dt[mask],
        }
    )
    return gaps.reset_index(drop=True)


def find_3day_gaps(df: pd.DataFrame, max_gap_hours: float = 72.0) -> pd.DataFrame:
    """SIMPaCT Kuralı 2: 3 günü (> 72 saat / 259.200 saniye) aşan büyük kesintileri tespit eder.

    Kaynak: Koçyiğit vd. (2025) SIMPaCT.
    Eşik: > 3 gün (72 saat).
    """
    dt_seconds = df["time"].diff().dt.total_seconds()
    threshold_seconds = max_gap_hours * 3600.0
    mask = dt_seconds > threshold_seconds
    gaps = pd.DataFrame(
        {
            "start": df["time"].shift(1)[mask],
            "end": df["time"][mask],
            "hours": dt_seconds[mask] / 3600.0,
            "seconds": dt_seconds[mask],
        }
    )
    return gaps.reset_index(drop=True)


def find_restarts(df: pd.DataFrame) -> pd.DataFrame:
    """Sıra numarası (seq) geriye giden yeniden başlatma (reboot) anlarını tespit eder."""
    if "seq" not in df.columns:
        return df.iloc[0:0]
    seq = pd.to_numeric(df["seq"], errors="coerce")
    return df[seq.diff() < 0]


def flatline_runs(series: pd.Series, min_len: int = 30) -> List[Tuple[int, int]]:
    """Aynı değerin en az min_len kez art arda tekrarlandığı indeks aralıklarını döndürür."""
    s = pd.to_numeric(series, errors="coerce")
    runs: List[Tuple[int, int]] = []
    start = None
    for i in range(1, len(s)):
        same = pd.notna(s.iloc[i]) and s.iloc[i] == s.iloc[i - 1]
        if same and start is None:
            start = i - 1
        if not same and start is not None:
            if i - start >= min_len:
                runs.append((start, i - 1))
            start = None
    if start is not None and len(s) - start >= min_len:
        runs.append((start, len(s) - 1))
    return runs


def check_120h_frozen(
    series: pd.Series,
    timestamps: Optional[pd.DatetimeIndex] = None,
    max_variation_pct: float = 1.0,
) -> pd.Series:
    """SIMPaCT Kuralı 3: 120 saat boyunca mutlak değişimi <%1 kalan donmuş değerleri bayraklar.

    Kaynak: Koçyiğit vd. (2025) SIMPaCT.
    Eşik: 120 saatlik kayan pencerede min-max değişimi < %1.0 ise arıza.
    """
    s = pd.to_numeric(series, errors="coerce")
    idx = timestamps if timestamps is not None else pd.date_range("2024-01-01", periods=len(s), freq="h")
    df = pd.DataFrame({"val": s.values}, index=idx)

    # 120 saatlik kayan pencerede min-max aralığı
    rolling_max = df["val"].rolling("120h", min_periods=24).max()
    rolling_min = df["val"].rolling("120h", min_periods=24).min()
    val_range = rolling_max - rolling_min
    mean_val = df["val"].rolling("120h", min_periods=24).mean().abs()

    pct_change = (val_range / np.maximum(mean_val, 1e-4)) * 100.0
    frozen_mask = (pct_change < max_variation_pct) & (pct_change >= 0.0)
    return pd.Series(frozen_mask.values, index=series.index)


def spikes(series: pd.Series, k: float = 6.0) -> pd.Index:
    """Robust medyan mutlak sapma (MAD) ölçeğine göre sıçramaları (spike) tespit eder."""
    s = pd.to_numeric(series, errors="coerce")
    d = s.diff().abs().round(6)
    med = float(np.nanmedian(d))
    mad = float(np.nanmedian(np.abs(d - med)))
    scale = 1.4826 * mad if np.isfinite(mad) and mad > 0 else float(np.nanstd(d))
    if not np.isfinite(scale) or scale == 0:
        return d.index[:0]
    return d.index[d > med + k * scale]


def spikes_rolling_median_24h(
    series: pd.Series,
    timestamps: Optional[pd.DatetimeIndex] = None,
    k: float = 4.0,
) -> pd.Series:
    """SIMPaCT Kuralı 4: 24 saatlik kayan medyana göre ani sıçramaları bayraklar.

    Kaynak: Koçyiğit vd. (2025) SIMPaCT.
    Eşik: |değer - 24h_medyan| > k * MAD.
    """
    s = pd.to_numeric(series, errors="coerce")
    idx = timestamps if timestamps is not None else pd.date_range("2024-01-01", periods=len(s), freq="h")
    df = pd.DataFrame({"val": s.values}, index=idx)

    med_24h = df["val"].rolling("24h", min_periods=6).median()
    diff = (df["val"] - med_24h).abs()
    mad = diff.rolling("24h", min_periods=6).median()
    scale = 1.4826 * mad
    scale = scale.replace(0.0, np.nan).fillna(float(np.nanstd(s)) or 0.01)

    is_spike = diff > (k * scale)
    return pd.Series(is_spike.values, index=series.index)


def check_physical_range(
    series: pd.Series,
    min_val: float,
    max_val: float,
) -> pd.Series:
    """SIMPaCT Kuralı 5: Fiziksel sınır dışındaki değerleri bayraklar."""
    s = pd.to_numeric(series, errors="coerce")
    return (s < min_val) | (s > max_val) | s.isna()


def run_rule_based_qc(
    df: pd.DataFrame,
    interval_s: float = 60.0,
    flat_min: int = 30,
) -> Dict[str, pd.Series]:
    """Tüm SIMPaCT kural tabanlı kalite kontrollerini koşturur ve bayrak sözlüğü döndürür."""
    flags: Dict[str, pd.Series] = {}
    time_idx = pd.DatetimeIndex(df["time"]) if "time" in df.columns else None

    for col in ["soil_raw", "soil_pct", "temp_c", "hum_pct", "soil_vwc"]:
        if col not in df.columns:
            continue

        # 1. Eksiklik bayrağı (> %50 pencere)
        missing_flag, _ = check_missing_rate(df[col])
        flags[f"{col}_excessive_missing"] = pd.Series(missing_flag, index=df.index)

        # 2. Donmuş değerler (art arda N tekrar ve 120 saatlik SIMPaCT kuralı)
        runs = flatline_runs(df[col], min_len=flat_min)
        flat_flag = pd.Series(False, index=df.index)
        for a, b in runs:
            flat_flag.iloc[a : b + 1] = True
        flags[f"{col}_flat"] = flat_flag

        if time_idx is not None and len(df) >= 24:
            flags[f"{col}_120h_frozen"] = check_120h_frozen(df[col], timestamps=time_idx)

        # 3. Sıçrama (24h kayan medyan ve ardışık MAD)
        sp = spikes(df[col])
        flags[f"{col}_spike"] = df.index.isin(sp)
        if time_idx is not None and len(df) >= 12:
            flags[f"{col}_spike_24h"] = spikes_rolling_median_24h(df[col], timestamps=time_idx)

    # 4. Fiziksel limit kontrolleri
    out_of_range = pd.Series(False, index=df.index)
    if "temp_c" in df.columns:
        out_of_range |= check_physical_range(df["temp_c"], 0.0, 50.0)
    if "hum_pct" in df.columns:
        out_of_range |= check_physical_range(df["hum_pct"], 20.0, 90.0)
    if "soil_raw" in df.columns:
        out_of_range |= check_physical_range(df["soil_raw"], 0.0, 1023.0)
    if "soil_vwc" in df.columns:
        out_of_range |= check_physical_range(df["soil_vwc"], 0.0, 0.60)
    flags["out_of_range"] = out_of_range

    # 5. Büyük boşluklar (> 3 gün)
    if time_idx is not None:
        gaps_3d = find_3day_gaps(df)
        flags["has_3day_gap"] = pd.Series(len(gaps_3d) > 0, index=df.index)

    # 6. Firmware hata bayrakları
    if "err" in df.columns:
        err = pd.to_numeric(df["err"], errors="coerce").fillna(0).astype(int)
        for bit, name in ERR_BITS.items():
            flags[f"err_{name}"] = (err & bit) > 0

    return flags
