"""Pydantic şemaları (REST API istek ve yanıt modelleri).

Sözleşme: docs/INTERFACES.md.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    mode: str = "local"


class ZoneResponse(BaseModel):
    zone_id: str
    park_id: str
    veg_type: str
    irrigation_type: str
    area_m2: float
    app_rate_mm_h: float
    valve_id: Optional[str] = None
    controller_id: Optional[str] = None
    water_source: str = "unknown"
    irrigated_fraction: float = 0.60


class ParkResponse(BaseModel):
    id: str
    name: str
    area_m2: float
    centroid_lon: float
    centroid_lat: float
    tur: str
    ilce: str
    zones: List[ZoneResponse]


class WeatherResponseItem(BaseModel):
    time: str
    temp_mean: float
    temp_max: float
    temp_min: float
    rh_mean: float
    wind_speed_2m_ms: float
    rain_mm: float
    rad_mj_m2: float
    eto_mm: float
    source: str = "synthetic"


class TelemetryItem(BaseModel):
    time: str
    node: str
    seq: int
    soil_raw: int
    soil_pct: float
    temp_c: Optional[float] = None
    hum_pct: Optional[float] = None
    pump_s: int = 0
    rssi: int = -60
    err: int = 0
    source: str = "synthetic"


class QCRequest(BaseModel):
    records: List[Dict[str, Any]]
    interval_s: float = 60.0
    flat_min: int = 30


class QCResponse(BaseModel):
    total_records: int
    gap_count: int
    restart_count: int
    out_of_range_count: int
    flags: Dict[str, List[bool]]


class SimulateRequest(BaseModel):
    park_id: str = "yildiz"
    season: int = 2024
    strategy: str = "S4"  # S0, S1, S2, S3, S4
    source: str = "auto"  # auto / era5 / synthetic
    params: Optional[Dict[str, Any]] = None


class SimulateResponse(BaseModel):
    park_id: str
    season: int
    strategy: str
    source: str = "synthetic"
    metrics: Dict[str, Any]
    daily_records: List[Dict[str, Any]]


class CompareRequest(BaseModel):
    park_id: str = "yildiz"
    season: int = 2024
    strategies: List[str] = ["S0", "S1", "S2", "S3", "S4"]
    source: str = "auto"  # auto / era5 / synthetic


class CompareResponse(BaseModel):
    park_id: str
    season: int
    source: str = "synthetic"
    critic_weights: Dict[str, float]
    ranked_strategies: List[Dict[str, Any]]


class SensitivityRequest(BaseModel):
    park_id: str = "yildiz"
    season: int = 2024
    method: str = "oat"  # 'oat' veya 'sobol'
    source: str = "auto"  # auto / era5 / synthetic


class SensitivityResponse(BaseModel):
    method: str
    source: str = "synthetic"
    results: List[Dict[str, Any]]


class TestbedStateResponse(BaseModel):
    node: str = "node01"
    last_seen: str
    soil_raw: int
    soil_vwc_measured: float
    depletion_estimated_mm: float
    ks_estimated: float
    last_command: str = "NONE"
    source: str = "synthetic"


class TestbedAdviceResponse(BaseModel):
    node: str = "node01"
    recommended_duration_s: int
    reason: str
    requires_approval: bool = True
    source: str = "synthetic"
