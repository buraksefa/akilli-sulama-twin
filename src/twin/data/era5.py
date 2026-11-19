"""ERA5-Land NetCDF veri yükleyicisi, birikimli değişken açma (deaccumulation) ve dönüşümler.

Kaynaklar:
- ECMWF ERA5-Land Dokümantasyonu (birikimli değişkenler 00 UTC'den itibaren birikir).
- FAO-56 Bölüm 3 & 4 (Birim dönüşümleri ve 2m rüzgâr hızı denklemi 47).
- Tetens / Magnus Bağıl Nem Formülasyonu (FAO-56 Denklem 11-12).
"""

import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd

from twin.config import DEFAULT_CONFIG

logger = logging.getLogger(__name__)

_ERA5_CFG = DEFAULT_CONFIG.era5

PARK_COORDINATES: Dict[str, Dict[str, float]] = {
    "yildiz": {
        "lat": float(_ERA5_CFG.yildiz_lat.value),
        "lon": float(_ERA5_CFG.yildiz_lon.value),
    },
    "macka": {
        "lat": float(_ERA5_CFG.macka_lat.value),
        "lon": float(_ERA5_CFG.macka_lon.value),
    },
}


def deaccumulate_era5_hourly(
    series: pd.Series,
    timestamps: pd.DatetimeIndex,
    clamp_min: float = 0.0,
) -> pd.Series:
    """ERA5-Land 00:00 UTC başlangıçlı birikimli serileri saatlik artış değerine çevirir.

    ERA5-Land'de yağış (tp) ve radyasyon (ssrd, strd) her gün 00:00 UTC'de sıfırlanır
    ve gün boyunca kümülatif olarak birikir.
    - 01:00 UTC değeri ilk 1 saatin toplamıdır.
    - 02:00 - 23:00 UTC için saatlik değer = val(t) - val(t-1) dir.
    - 00:00 UTC değeri bir önceki günün 24. saatinin toplam birikimini temsil eder
      ve val(00:00) - val(23:00_onceki_gun) olarak ayrıştırılır.
    - Ay başı ve sonu sınırlarında önceki saat mevcut değilse kümülatif değer doğrudan alınır.

    Parametreler:
        series: Ham birikimli seri (örn: m cinsinden tp veya J/m2 cinsinden ssrd/strd).
        timestamps: Serinin UTC zaman damgaları.
        clamp_min: Sayısal yuvarlama kaynaklı negatif değerleri kırpma tabanı (varsayılan 0.0).

    Döndürür:
        Saatlik ayrıştırılmış pandas.Series.
    """
    if len(series) == 0:
        return pd.Series([], index=timestamps, dtype=float, name=series.name)

    vals = np.asarray(series.values, dtype=float)
    n = len(vals)
    deaccum = np.zeros(n, dtype=float)

    for i in range(n):
        t = timestamps[i]
        curr_val = vals[i]

        if t.hour == 1:
            # Günün ilk saati (01:00 UTC) -> doğrudan değer
            hourly_val = curr_val
        elif t.hour == 0:
            # 00:00 UTC: bir önceki günün 24. saatini (23:00-00:00 UTC) temsil eder.
            # Eğer önceki ay/gün dosyası mevcutsa (i > 0 ve prev_t ardışık ise),
            # val(00:00) - val(önceki ayın 23:00) olarak hesapla.
            # Önceki ay dosyası yoksa (i == 0 veya kesinti), bu satırı artış olarak kullanma (0.0 yap).
            if i == 0:
                hourly_val = 0.0
            else:
                prev_t = timestamps[i - 1]
                time_diff_hours = (t - prev_t).total_seconds() / 3600.0
                if 0.9 <= time_diff_hours <= 1.1:
                    hourly_val = curr_val - vals[i - 1]
                else:
                    hourly_val = 0.0
        else:
            if i == 0:
                hourly_val = curr_val
            else:
                prev_t = timestamps[i - 1]
                time_diff_hours = (t - prev_t).total_seconds() / 3600.0
                if 0.9 <= time_diff_hours <= 1.1:
                    # Kesintisiz 1 saatlik ardışık adım
                    hourly_val = curr_val - vals[i - 1]
                else:
                    # Veri boşluğu / kesinti durumunda kümülatif değeri doğrudan al
                    hourly_val = curr_val

        if clamp_min is not None:
            hourly_val = max(clamp_min, hourly_val)

        deaccum[i] = hourly_val

    return pd.Series(deaccum, index=timestamps, name=series.name)


def kelvin_to_celsius(temp_k: Union[float, np.ndarray, pd.Series]) -> Union[float, np.ndarray, pd.Series]:
    """Kelvin sıcaklığı Santigrat dereceye çevirir (T_C = T_K - 273.15)."""
    offset = float(_ERA5_CFG.kelvin_offset.value)
    return temp_k - offset


def meters_to_mm(precip_m: Union[float, np.ndarray, pd.Series]) -> Union[float, np.ndarray, pd.Series]:
    """Metre cinsinden yağışı milimetreye çevirir (P_mm = P_m * 1000)."""
    return precip_m * 1000.0


def joules_m2_to_watts_m2(
    ssrd_j_m2: Union[float, np.ndarray, pd.Series], dt_seconds: float = 3600.0
) -> Union[float, np.ndarray, pd.Series]:
    """J/m2 cinsinden saatlik güneş enerjisini W/m2 akısına çevirir (W/m2 = (J/m2) / 3600s)."""
    return ssrd_j_m2 / dt_seconds


def joules_m2_to_mj_m2(ssrd_j_m2: Union[float, np.ndarray, pd.Series]) -> Union[float, np.ndarray, pd.Series]:
    """J/m2 değerini MJ/m2 birimine çevirir (MJ/m2 = J/m2 / 1e6)."""
    return ssrd_j_m2 / 1.0e6


def wind10m_to_wind2m(u10: Union[float, np.ndarray, pd.Series]) -> Union[float, np.ndarray, pd.Series]:
    """10 metre rüzgâr hızını FAO-56 Denklem 47 ile 2 metre standart yüksekliğe dönüştürür.

    Denklem: u2 = u10 * 4.87 / ln(67.8 * 10 - 5.42) ≈ u10 * 0.7480
    Kaynak: FAO-56 Denklem 47 (Logaritmik rüzgâr profili).
    """
    factor = 4.87 / math.log(67.8 * 10.0 - 5.42)
    return u10 * factor


def relative_humidity_from_dewpoint(
    temp_c: Union[float, np.ndarray, pd.Series],
    dewpoint_c: Union[float, np.ndarray, pd.Series],
) -> Union[float, np.ndarray, pd.Series]:
    """Hava ve çiy noktası sıcaklığından bağıl nem (%) hesaplar.

    Kaynak: FAO-56 Denklem 11-12, Tetens formülü.
    """
    es = 0.6108 * np.exp((17.27 * temp_c) / (temp_c + 237.3))
    ea = 0.6108 * np.exp((17.27 * dewpoint_c) / (dewpoint_c + 237.3))
    rh = 100.0 * (ea / es)
    if isinstance(rh, (pd.Series, np.ndarray)):
        return np.clip(rh, 0.0, 100.0)
    return min(100.0, max(0.0, float(rh)))


def _extract_variable(
    ds: Any, var_names: List[str], default_val: Optional[float] = None
) -> Optional[np.ndarray]:
    """xarray Dataset içinden olası alternatif değişken isimlerine göre veriyi çeker."""
    for name in var_names:
        if name in ds.data_vars or name in ds.variables:
            arr = ds[name].values
            # Boyut indirgeme (fazladan 1 boyutlu koordinatları sıkıştır)
            arr = np.squeeze(arr)
            return arr
    if default_val is not None:
        return default_val
    return None


def load_era5_netcdf(
    nc_input: Union[str, Path, List[Union[str, Path]], Any],
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    park_id: Optional[str] = None,
) -> pd.DataFrame:
    """ERA5-Land NetCDF dosyasını/dosyalarını okur, en yakın ızgara hücresini seçer ve dönüştürür.

    Parametreler:
        nc_input: NetCDF dosya yolu, yollar listesi, klasör yolu veya xarray Dataset.
        lat: Enlem (None ise park_id veya merkez kullanılır).
        lon: Boylam (None ise park_id veya merkez kullanılır).
        park_id: 'yildiz' veya 'macka' (verilirse koordinatları otomatik alır).

    Döndürür:
        Saatlik ayrıştırılmış ve birimleri dönüştürülmüş pandas.DataFrame.
    """
    import xarray as xr

    # Park koordinatlarını belirle
    if park_id is not None and park_id in PARK_COORDINATES:
        target_lat = PARK_COORDINATES[park_id]["lat"]
        target_lon = PARK_COORDINATES[park_id]["lon"]
    else:
        target_lat = lat
        target_lon = lon

    # Girdi tipine göre xarray Dataset aç
    if isinstance(nc_input, xr.Dataset):
        ds = nc_input
    elif isinstance(nc_input, (list, tuple)):
        file_list = [Path(p) for p in nc_input]
        if not file_list:
            raise FileNotFoundError("Dosya listesi boş.")
        if len(file_list) == 1:
            ds = xr.open_dataset(file_list[0])
        else:
            datasets = [xr.open_dataset(f) for f in file_list]
            time_dim = "valid_time" if "valid_time" in datasets[0].coords else "time"
            ds = xr.concat(datasets, dim=time_dim)
    else:
        path = Path(nc_input)
        if path.is_dir():
            files = sorted(path.glob("era5land_*.nc"))
            if not files:
                raise FileNotFoundError(f"Dizinde ERA5 NetCDF dosyası bulunamadı: {path}")
            if len(files) == 1:
                ds = xr.open_dataset(files[0])
            else:
                datasets = [xr.open_dataset(f) for f in files]
                time_dim = "valid_time" if "valid_time" in datasets[0].coords else "time"
                ds = xr.concat(datasets, dim=time_dim)
        else:
            if not path.is_file():
                raise FileNotFoundError(f"ERA5 NetCDF dosyası bulunamadı: {path}")
            ds = xr.open_dataset(path)

    # Mekansal ızgara seçimi (en yakın hücre veya alan ortalaması)
    lat_dim = "latitude" if "latitude" in ds.coords else ("lat" if "lat" in ds.coords else None)
    lon_dim = "longitude" if "longitude" in ds.coords else ("lon" if "lon" in ds.coords else None)

    if lat_dim and lon_dim:
        if target_lat is not None and target_lon is not None:
            ds = ds.sel({lat_dim: target_lat, lon_dim: target_lon}, method="nearest")
        else:
            ds = ds.mean(dim=[lat_dim, lon_dim])

    # Zaman koordinatı: valid_time veya time
    time_coord = "valid_time" if "valid_time" in ds.coords else "time"
    if time_coord not in ds.coords:
        raise KeyError(
            f"NetCDF içinde zaman koordinatı bulunamadı ('valid_time' veya 'time' bekleniyor). Mevcut: {list(ds.coords)}"
        )

    times = pd.to_datetime(ds[time_coord].values, utc=True)

    # Değişkenleri çek
    t2m_k = _extract_variable(ds, ["t2m", "2t", "2m_temperature"])
    d2m_k = _extract_variable(ds, ["d2m", "2d", "2m_dewpoint_temperature"])
    u10 = _extract_variable(ds, ["u10", "10u", "10m_u_component_of_wind"], default_val=np.zeros(len(times)))
    v10 = _extract_variable(ds, ["v10", "10v", "10m_v_component_of_wind"], default_val=np.zeros(len(times)))
    sp_pa = _extract_variable(ds, ["sp", "surface_pressure"], default_val=np.full(len(times), 101325.0))
    tp_raw_m = _extract_variable(ds, ["tp", "total_precipitation"], default_val=np.zeros(len(times)))
    ssrd_raw_j = _extract_variable(
        ds, ["ssrd", "surface_solar_radiation_downwards"], default_val=np.zeros(len(times))
    )
    strd_raw_j = _extract_variable(ds, ["strd", "surface_thermal_radiation_downwards"])
    swvl1_val = _extract_variable(ds, ["swvl1", "volumetric_soil_water_layer_1"])
    swvl2_val = _extract_variable(ds, ["swvl2", "volumetric_soil_water_layer_2"])

    if t2m_k is None or d2m_k is None:
        raise ValueError("NetCDF içinde kritik sıcaklık değişkenleri (t2m/d2m) eksik.")

    # Birim dönüşümleri
    t2m_c = kelvin_to_celsius(t2m_k)
    d2m_c = kelvin_to_celsius(d2m_k)
    wind10 = np.sqrt(u10**2 + v10**2)
    wind2 = wind10m_to_wind2m(wind10)
    rh_pct = relative_humidity_from_dewpoint(t2m_c, d2m_c)
    sp_kpa = sp_pa / 1000.0

    # Deaccumulation (yağış ve radyasyon serileri)
    tp_deaccum_m = deaccumulate_era5_hourly(pd.Series(tp_raw_m, index=times), times).values
    rain_mm = meters_to_mm(tp_deaccum_m)

    ssrd_deaccum_j = deaccumulate_era5_hourly(pd.Series(ssrd_raw_j, index=times), times).values
    ssrd_wm2 = joules_m2_to_watts_m2(ssrd_deaccum_j)
    ssrd_mj_m2 = joules_m2_to_mj_m2(ssrd_deaccum_j)

    data_dict = {
        "temp_c": t2m_c,
        "dewpoint_c": d2m_c,
        "rh_pct": rh_pct,
        "wind_speed_2m_ms": wind2,
        "pressure_kpa": sp_kpa,
        "rain_mm": rain_mm,
        "rad_wm2": ssrd_wm2,
        "rad_mj_m2": ssrd_mj_m2,
    }

    if strd_raw_j is not None:
        strd_deaccum_j = deaccumulate_era5_hourly(pd.Series(strd_raw_j, index=times), times).values
        data_dict["strd_wm2"] = joules_m2_to_watts_m2(strd_deaccum_j)
        data_dict["strd_mj_m2"] = joules_m2_to_mj_m2(strd_deaccum_j)

    if swvl1_val is not None:
        data_dict["volumetric_soil_water_layer_1"] = swvl1_val
    if swvl2_val is not None:
        data_dict["volumetric_soil_water_layer_2"] = swvl2_val

    df = pd.DataFrame(data_dict, index=times)
    df.index.name = "time"
    # Zamana göre sırala ve kopyaları kaldır
    df = df[~df.index.duplicated(keep="first")].sort_index()
    return df


def aggregate_hourly_to_daily(hourly_df: pd.DataFrame) -> pd.DataFrame:
    """Saatlik meteoroloji serisini FAO-56 Penman-Monteith için günlük özete dönüştürür.

    Döndürülen günlük değişkenler:
    - temp_mean, temp_max, temp_min (°C)
    - rh_mean, rh_max, rh_min (%)
    - wind_speed_2m_ms (ortalama m/s)
    - pressure_kpa (ortalama kPa)
    - rain_mm (günlük toplam mm)
    - rad_mj_m2 (günlük toplam MJ/m2/gün)
    - rad_wm2 (günlük ortalama W/m2)
    - volumetric_soil_water_layer_1 / swvl1 (günlük ortalama m3/m3, varsa)
    - volumetric_soil_water_layer_2 / swvl2 (günlük ortalama m3/m3, varsa)
    """
    daily = pd.DataFrame(index=hourly_df.resample("D").mean().index)
    daily["temp_mean"] = hourly_df["temp_c"].resample("D").mean()
    daily["temp_max"] = hourly_df["temp_c"].resample("D").max()
    daily["temp_min"] = hourly_df["temp_c"].resample("D").min()

    daily["rh_mean"] = hourly_df["rh_pct"].resample("D").mean()
    daily["rh_max"] = hourly_df["rh_pct"].resample("D").max()
    daily["rh_min"] = hourly_df["rh_pct"].resample("D").min()

    daily["wind_speed_2m_ms"] = hourly_df["wind_speed_2m_ms"].resample("D").mean()
    daily["pressure_kpa"] = hourly_df["pressure_kpa"].resample("D").mean()
    daily["rain_mm"] = hourly_df["rain_mm"].resample("D").sum()
    daily["rad_mj_m2"] = hourly_df["rad_mj_m2"].resample("D").sum()
    daily["rad_wm2"] = hourly_df["rad_wm2"].resample("D").mean()

    # İsteğe bağlı toprak nemi katmanları
    if "volumetric_soil_water_layer_1" in hourly_df.columns:
        daily["swvl1"] = hourly_df["volumetric_soil_water_layer_1"].resample("D").mean()
    elif "swvl1" in hourly_df.columns:
        daily["swvl1"] = hourly_df["swvl1"].resample("D").mean()

    if "volumetric_soil_water_layer_2" in hourly_df.columns:
        daily["swvl2"] = hourly_df["volumetric_soil_water_layer_2"].resample("D").mean()
    elif "swvl2" in hourly_df.columns:
        daily["swvl2"] = hourly_df["swvl2"].resample("D").mean()

    if "strd_mj_m2" in hourly_df.columns:
        daily["strd_mj_m2"] = hourly_df["strd_mj_m2"].resample("D").sum()

    return daily.dropna(subset=["temp_mean", "rain_mm", "rad_mj_m2"])


def build_era5_processed_dataset(
    raw_dir: Union[str, Path] = "data/raw/era5",
    processed_dir: Union[str, Path] = "data/processed",
    years: Optional[List[int]] = None,
    park_ids: Optional[List[str]] = None,
) -> Dict[str, pd.DataFrame]:
    """data/raw/era5 altındaki ham NetCDF dosyalarını işleyip data/processed altına CSV olarak kaydeder."""
    from twin.model.et0 import fao56_penman_monteith_daily

    raw_path = Path(raw_dir)
    proc_path = Path(processed_dir)
    proc_path.mkdir(parents=True, exist_ok=True)

    target_parks = park_ids or ["yildiz", "macka"]
    files = sorted(raw_path.glob("era5land_*.nc"))
    if not files:
        logger.warning("data/raw/era5 dizininde NetCDF dosyası bulunamadı: %s", raw_path)
        return {}

    # Dosyalardaki yılları tespit et
    found_years = set()
    for f in files:
        parts = f.stem.split("_")
        if len(parts) >= 2 and parts[1].isdigit():
            found_years.add(int(parts[1]))

    filter_years = sorted(found_years if years is None else set(years).intersection(found_years))
    results: Dict[str, pd.DataFrame] = {}

    for park in target_parks:
        for y in filter_years:
            year_files = sorted(raw_path.glob(f"era5land_{y:04d}_*.nc"))
            if not year_files:
                continue

            logger.info("İşleniyor: Park=%s, Yıl=%d (%d dosya)...", park, y, len(year_files))
            hourly_df = load_era5_netcdf(year_files, park_id=park)
            daily_df = aggregate_hourly_to_daily(hourly_df)

            # ETo hesapla
            doy = daily_df.index.dayofyear.values
            lat = PARK_COORDINATES.get(park, {}).get("lat", 41.04)
            eto_vals = fao56_penman_monteith_daily(
                temp_mean_c=daily_df["temp_mean"].values,
                temp_max_c=daily_df["temp_max"].values,
                temp_min_c=daily_df["temp_min"].values,
                wind_speed_2m_ms=daily_df["wind_speed_2m_ms"].values,
                rad_mj_m2_day=daily_df["rad_mj_m2"].values,
                rh_mean_pct=daily_df["rh_mean"].values,
                day_of_year=doy,
                latitude_deg=lat,
            )
            daily_df["eto_mm"] = eto_vals

            out_csv = proc_path / f"era5_{park}_{y}.csv"
            daily_df.to_csv(out_csv)
            logger.info("✅ Kaydedildi: %s (%d gün)", out_csv, len(daily_df))
            results[f"{park}_{y}"] = daily_df

    return results


def load_era5_season(
    season_year: int = 2024,
    park_id: str = "yildiz",
    raw_dir: Union[str, Path] = "data/raw/era5",
    processed_dir: Union[str, Path] = "data/processed",
) -> pd.DataFrame:
    """Belirli bir park ve sezon yılı için gerçek ERA5-Land günlük verisini yükler.

    Önce data/processed/era5_{park}_{year}.csv dosyasına bakar. Bulamazsa data/raw/era5/
    altındaki NetCDF dosyalarından anında derler. Dosyalar yoksa FileNotFoundError fırlatır.
    """
    from twin.model.et0 import fao56_penman_monteith_daily

    proc_file = Path(processed_dir) / f"era5_{park_id}_{season_year}.csv"
    if proc_file.is_file():
        df = pd.read_csv(proc_file, index_col=0, parse_dates=True)
        # 1 Nisan - 31 Ekim sulama sezonunu filtrele
        start_date = f"{season_year}-04-01"
        end_date = f"{season_year}-10-31"
        return df.loc[(df.index >= start_date) & (df.index <= end_date)]

    raw_path = Path(raw_dir)
    raw_files = sorted(raw_path.glob(f"era5land_{season_year:04d}_*.nc"))
    if not raw_files:
        raise FileNotFoundError(
            f"ERA5 verisi bulunamadı (park='{park_id}', season={season_year}).\n"
            f"Aranan dosyalar: {proc_file} veya {raw_path}/era5land_{season_year}_*.nc\n"
            f"Lütfen 'twin era5 download --park {park_id} --years {season_year}' komutuyla veriyi indirin."
        )

    hourly_df = load_era5_netcdf(raw_files, park_id=park_id)
    daily_df = aggregate_hourly_to_daily(hourly_df)

    # ETo hesapla
    doy = daily_df.index.dayofyear.values
    lat = PARK_COORDINATES.get(park_id, {}).get("lat", 41.04)
    eto_vals = fao56_penman_monteith_daily(
        temp_mean_c=daily_df["temp_mean"].values,
        temp_max_c=daily_df["temp_max"].values,
        temp_min_c=daily_df["temp_min"].values,
        wind_speed_2m_ms=daily_df["wind_speed_2m_ms"].values,
        rad_mj_m2_day=daily_df["rad_mj_m2"].values,
        rh_mean_pct=daily_df["rh_mean"].values,
        day_of_year=doy,
        latitude_deg=lat,
    )
    daily_df["eto_mm"] = eto_vals

    start_date = f"{season_year}-04-01"
    end_date = f"{season_year}-10-31"
    return daily_df.loc[(daily_df.index >= start_date) & (daily_df.index <= end_date)]


def generate_synthetic_era5(
    start_date: str = "2024-04-01",
    end_date: str = "2024-10-31",
    seed: int = 42,
    lat: float = 41.04,
) -> pd.DataFrame:
    """Testler ve simülasyonlar için deterministik sentetik saatlik ERA5 meteoroloji verisi üretir.

    İstanbul yaz iklim özelliklerini yansıtır (Nisan-Ekim dönemi).
    """
    rng = np.random.default_rng(seed)
    times = pd.date_range(start=start_date, end=end_date, freq="h", tz="UTC")
    n = len(times)

    # Gün içi ve mevsimsel sıcaklık dalgalanması
    day_of_year = times.dayofyear.values
    hour = times.hour.values

    # Yaz ortası (Temmuz) zirve yapan mevsimsel eğri
    seasonal_temp = 14.0 + 12.0 * np.sin((day_of_year - 100) / 215.0 * np.pi)
    diurnal_temp = 5.0 * np.sin((hour - 8) / 24.0 * 2.0 * np.pi)
    temp_noise = rng.normal(0, 1.2, n)
    temp_c = seasonal_temp + diurnal_temp + temp_noise

    # Bağıl nem (sıcaklıkla ters orantılı)
    rh_base = 80.0 - 25.0 * np.sin((hour - 8) / 24.0 * 2.0 * np.pi)
    rh_noise = rng.normal(0, 4.0, n)
    rh_pct = np.clip(rh_base + rh_noise, 25.0, 98.0)

    # Çiy noktası sıcaklığı
    # Td ≈ T - ((100 - RH)/5)
    dewpoint_c = temp_c - ((100.0 - rh_pct) / 5.0)

    # Rüzgâr hızı (m/s)
    wind2 = np.clip(rng.weibull(2.0, n) * 2.5 + 0.5, 0.2, 12.0)

    # Yüzey basıncı (kPa)
    sp_kpa = 101.3 + rng.normal(0, 0.4, n)

    # Güneş radyasyonu (W/m2 ve MJ/m2/saat)
    # Güneş yalnızca 05:00 - 19:00 arası
    solar_elevation = np.sin((hour - 6) / 14.0 * np.pi)
    solar_elevation = np.where((hour >= 6) & (hour <= 19), solar_elevation, 0.0)
    rad_wm2 = np.clip(solar_elevation * (750.0 + rng.normal(0, 30.0, n)), 0.0, 1000.0)
    rad_mj_m2 = rad_wm2 * 3600.0 / 1.0e6

    # Yağış (mm/saat) - ara sıra yaz fırtınaları / yağış olayları
    rain_mm = np.zeros(n)
    rain_events = rng.random(n) < 0.03  # %3 saatte yağış
    rain_mm[rain_events] = rng.exponential(scale=2.5, size=int(rain_events.sum()))
    rain_mm = np.round(rain_mm, 2)

    df = pd.DataFrame(
        {
            "temp_c": temp_c,
            "dewpoint_c": dewpoint_c,
            "rh_pct": rh_pct,
            "wind_speed_2m_ms": wind2,
            "pressure_kpa": sp_kpa,
            "rain_mm": rain_mm,
            "rad_wm2": rad_wm2,
            "rad_mj_m2": rad_mj_m2,
        },
        index=times,
    )
    df.index.name = "time"
    return df
