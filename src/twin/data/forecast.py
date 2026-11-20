"""Open-Meteo günlük hava tahmini yükleyicisi (anahtar gerektirmez).

Kaynak: https://open-meteo.com/en/docs (Forecast API). Kullanılan günlük alanlar:
`et0_fao_evapotranspiration` (FAO-56 referans ETo, mm), `precipitation_sum` (mm),
`precipitation_probability_max` (%), `temperature_2m_max/min` (°C).

Not: `past_days` ile gelen geçmiş günler istasyon ölçümü değil, Open-Meteo'nun model analizidir
(etiket `open_meteo_past`); bugün ve sonrası tahmindir (`open_meteo_forecast`). Sunucuya yalnız park
koordinatı gönderilir.
"""

from datetime import date
from typing import Optional

import pandas as pd
import requests

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
DAILY_FIELDS = {
    "et0_fao_evapotranspiration": "eto_mm",
    "precipitation_sum": "rain_mm",
    "precipitation_probability_max": "rain_prob_pct",
    "temperature_2m_max": "temp_max",
    "temperature_2m_min": "temp_min",
}
TIMEZONE = "Europe/Istanbul"


def parse_open_meteo_daily(payload: dict, today: date) -> pd.DataFrame:
    """Open-Meteo JSON yanıtını günlük DataFrame'e çevirir; `is_forecast` = tarih ≥ bugün."""
    daily = payload["daily"]
    df = pd.DataFrame({new: daily[old] for old, new in DAILY_FIELDS.items() if old in daily})
    df.index = pd.to_datetime(daily["time"])
    df.index.name = "time"
    df["is_forecast"] = df.index.date >= today
    df["source"] = df["is_forecast"].map({True: "open_meteo_forecast", False: "open_meteo_past"})
    df = df.astype({c: float for c in DAILY_FIELDS.values() if c in df.columns})
    if "rain_prob_pct" in df.columns:
        df.loc[~df["is_forecast"], "rain_prob_pct"] = 100.0  # gerçekleşmiş (analiz) yağış kesin kabul edilir
    df.attrs["source"] = "open_meteo"
    df.attrs["grid_latitude"] = payload.get("latitude")
    df.attrs["grid_longitude"] = payload.get("longitude")
    return df


def fetch_open_meteo_daily(
    latitude: float,
    longitude: float,
    past_days: int = 92,
    forecast_days: int = 7,
    today: Optional[date] = None,
    timeout_s: float = 20.0,
) -> pd.DataFrame:
    """Geçmiş `past_days` gün (model analizi) ve bugünden itibaren `forecast_days` gün tahmini getirir."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": ",".join(DAILY_FIELDS),
        "past_days": past_days,
        "forecast_days": forecast_days,
        "timezone": TIMEZONE,
    }
    resp = requests.get(OPEN_METEO_URL, params=params, timeout=timeout_s)
    resp.raise_for_status()
    return parse_open_meteo_daily(resp.json(), today or pd.Timestamp.now(tz=TIMEZONE).date())


PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"


def parse_previous_runs_hourly(payload: dict, leads: range) -> pd.DataFrame:
    """Saatlik önceki-koşu yanıtını günlük toplamlara çevirir (UTC günleri, ERA5 ile aynı sınır).

    Sütunlar: `eto_d{k}`, `rain_d{k}` = k gün önce yayımlanmış tahminin o güne ait toplamı [mm].
    k = 0 en güncel koşudur. Bir günün herhangi bir saati eksikse o günün değeri NaN olur.
    """
    hourly = payload["hourly"]
    idx = pd.to_datetime(hourly["time"])
    cols = {}
    for k in leads:
        suffix = "" if k == 0 else f"_previous_day{k}"
        cols[f"eto_d{k}"] = hourly[f"et0_fao_evapotranspiration{suffix}"]
        cols[f"rain_d{k}"] = hourly[f"precipitation{suffix}"]
    df = pd.DataFrame(cols, index=idx).astype(float)
    daily = df.resample("D").sum(min_count=24)
    daily.index.name = "time"
    daily.attrs["source"] = "open_meteo_previous_runs"
    daily.attrs["grid_latitude"] = payload.get("latitude")
    daily.attrs["grid_longitude"] = payload.get("longitude")
    return daily


def fetch_previous_runs_daily(
    latitude: float,
    longitude: float,
    start: str,
    end: str,
    leads: range = range(0, 8),
    timeout_s: float = 60.0,
) -> pd.DataFrame:
    """Open-Meteo Previous Runs API: k gün önceden yapılmış tahminlerin günlük toplamları (UTC)."""
    hourly = []
    for k in leads:
        suffix = "" if k == 0 else f"_previous_day{k}"
        hourly += [f"et0_fao_evapotranspiration{suffix}", f"precipitation{suffix}"]
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start,
        "end_date": end,
        "hourly": ",".join(hourly),
        "timezone": "GMT",
    }
    resp = requests.get(PREVIOUS_RUNS_URL, params=params, timeout=timeout_s)
    resp.raise_for_status()
    return parse_previous_runs_hourly(resp.json(), leads)
