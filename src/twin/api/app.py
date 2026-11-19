"""FastAPI REST API Servisi.

Sözleşme: docs/INTERFACES.md.
Güvenlik: Yalnızca yerel ağ (localhost), Bearer token kimlik doğrulaması.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from twin.api.schemas import (
    CompareRequest,
    CompareResponse,
    HealthResponse,
    ParkResponse,
    QCRequest,
    QCResponse,
    SensitivityRequest,
    SensitivityResponse,
    SimulateRequest,
    SimulateResponse,
    TelemetryItem,
    TestbedAdviceResponse,
    TestbedStateResponse,
    WeatherResponseItem,
    ZoneResponse,
)
from twin.data.parks import get_default_zones, load_parks
from twin.qc import find_gaps, find_restarts, run_rule_based_qc
from twin.sim import (
    compare_all_strategies,
    get_all_strategies,
    prepare_season_weather,
    run_oat_sensitivity,
    run_sobol_morris_sampling,
    simulate_strategy_season,
)

app = FastAPI(
    title="Akıllı Sulama Dijital İkiz API",
    description="Galatasaray Üniversitesi Yüksek Lisans Tezi Kentsel Yeşil Alan Sulama Karar Desteği REST API Servisi",
    version="0.1.0",
)

security = HTTPBearer(auto_error=False)


def get_api_secret_token() -> str:
    """Ortam değişkeninden API yetkilendirme anahtarını alır.

    Tanımlı değilse servis güvenlik gereği hata verir ve çalışmayı durdurur.
    """
    token = os.environ.get("API_AUTH_TOKEN")
    if not token or not token.strip():
        raise RuntimeError(
            "GÜVENLİK HATASI: 'API_AUTH_TOKEN' ortam değişkeni tanımlı değil. "
            "Servis güvensiz veya varsayılan anahtarla çalıştırılamaz. "
            "Lütfen .env dosyasını veya sistem ortam değişkenlerini yapılandırın."
        )
    return token.strip()


def verify_token(credentials: Optional[HTTPAuthorizationCredentials] = Security(security)):
    """Bearer token doğrulaması."""
    expected_token = get_api_secret_token()
    token = credentials.credentials if credentials else None
    if not token or token != expected_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Geçersiz veya eksik API yetkilendirme anahtarı (Bearer token).",
        )
    return token


@app.get("/health", response_model=HealthResponse)
def get_health():
    """Servis sağlık ve sürüm kontrolü."""
    return HealthResponse(status="ok", version="0.1.0", mode="local")


@app.get("/parks", response_model=List[ParkResponse], dependencies=[Depends(verify_token)])
def get_parks():
    """Kayıtlı park listesi ve poligon metadata bilgileri."""
    parks = load_parks()
    out = []
    for pid, p in parks.items():
        zones = [
            ZoneResponse(
                zone_id=z.zone_id,
                park_id=z.park_id,
                veg_type=z.veg_type,
                irrigation_type=z.irrigation_type,
                area_m2=z.area_m2,
                app_rate_mm_h=z.app_rate_mm_h,
                water_source=z.water_source,
                irrigated_fraction=z.irrigated_fraction,
            )
            for z in p.zones
        ]
        out.append(
            ParkResponse(
                id=p.id,
                name=p.name,
                area_m2=p.area_m2,
                centroid_lon=p.centroid_lon,
                centroid_lat=p.centroid_lat,
                tur=p.tur,
                ilce=p.ilce,
                zones=zones,
            )
        )
    return out


@app.get("/parks/{park_id}/zones", response_model=List[ZoneResponse], dependencies=[Depends(verify_token)])
def get_park_zones(park_id: str):
    """Belirli bir park için sulama bölgeleri (zones)."""
    zones = get_default_zones(park_id)
    return [
        ZoneResponse(
            zone_id=z.zone_id,
            park_id=z.park_id,
            veg_type=z.veg_type,
            irrigation_type=z.irrigation_type,
            area_m2=z.area_m2,
            app_rate_mm_h=z.app_rate_mm_h,
            water_source=z.water_source,
            irrigated_fraction=z.irrigated_fraction,
        )
        for z in zones
    ]


@app.get("/weather", response_model=List[WeatherResponseItem], dependencies=[Depends(verify_token)])
def get_weather(park_id: str = "yildiz", season: int = 2024, source: str = "auto"):
    """Park için sezonluk ERA5 meteoroloji ve ETo zaman serisi."""
    parks = load_parks()
    park = parks.get(park_id, None)
    lat = park.centroid_lat if park else 41.04
    try:
        df = prepare_season_weather(
            season_year=season,
            latitude_deg=lat,
            source=source,
            park_id=park_id,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    resolved_source = df.attrs.get("source", "unknown")
    records = []
    for idx, row in df.iterrows():
        records.append(
            WeatherResponseItem(
                time=str(idx),
                temp_mean=round(float(row["temp_mean"]), 2),
                temp_max=round(float(row["temp_max"]), 2),
                temp_min=round(float(row["temp_min"]), 2),
                rh_mean=round(float(row["rh_mean"]), 1),
                wind_speed_2m_ms=round(float(row["wind_speed_2m_ms"]), 2),
                rain_mm=round(float(row["rain_mm"]), 2),
                rad_mj_m2=round(float(row["rad_mj_m2"]), 2),
                eto_mm=round(float(row["eto_mm"]), 2),
                source=resolved_source,
            )
        )
    return records


@app.get("/telemetry", response_model=List[TelemetryItem], dependencies=[Depends(verify_token)])
def get_telemetry(node: str = "node01", limit: int = 100):
    """Testbed telemetri serisi (sentetik/InfluxDB)."""
    now = datetime.now(timezone.utc)
    times = pd.date_range(end=now, periods=limit, freq="min", tz="UTC")
    rng = np.random.default_rng(42)

    items = []
    for i, t in enumerate(times):
        raw = int(500 + 30 * np.sin(i / 10.0) + rng.normal(0, 3))
        items.append(
            TelemetryItem(
                time=t.isoformat(),
                node=node,
                seq=i + 1,
                soil_raw=raw,
                soil_pct=round(float((1023 - raw) / 1023.0 * 100), 1),
                temp_c=round(float(22.0 + rng.normal(0, 0.5)), 1),
                hum_pct=round(float(45.0 + rng.normal(0, 1.0)), 1),
                pump_s=0,
                rssi=-62,
                err=0,
                source="synthetic",
            )
        )
    return items


@app.post("/qc", response_model=QCResponse, dependencies=[Depends(verify_token)])
def post_qc(req: QCRequest):
    """Sensör zaman serisi için kalite kontrol ve arıza bayrakları raporu."""
    if not req.records:
        raise HTTPException(status_code=400, detail="Boş kayıt listesi gönderildi.")

    df = pd.DataFrame(req.records)
    if "time" not in df.columns and "pc_time_utc" not in df.columns:
        df["time"] = pd.date_range(end=datetime.now(timezone.utc), periods=len(df), freq="min")
    else:
        tcol = "time" if "time" in df.columns else "pc_time_utc"
        df["time"] = pd.to_datetime(df[tcol], utc=True)

    df = df.sort_values("time").reset_index(drop=True)
    gaps = find_gaps(df, req.interval_s)
    restarts = find_restarts(df)
    flags_dict = run_rule_based_qc(df, req.interval_s, req.flat_min)

    serializable_flags = {k: v.tolist() for k, v in flags_dict.items()}
    out_of_range_cnt = int(flags_dict.get("out_of_range", pd.Series([False])).sum())

    return QCResponse(
        total_records=len(df),
        gap_count=len(gaps),
        restart_count=len(restarts),
        out_of_range_count=out_of_range_cnt,
        flags=serializable_flags,
    )


@app.post("/simulate", response_model=SimulateResponse, dependencies=[Depends(verify_token)])
def post_simulate(req: SimulateRequest):
    """Tekil sulama stratejisi simülasyonu."""
    strategies = get_all_strategies()
    strat = strategies.get(req.strategy)
    if strat is None:
        raise HTTPException(
            status_code=400, detail=f"Bilinmeyen strateji: {req.strategy}. Seçenekler: S0, S1, S2, S3, S4"
        )

    parks = load_parks()
    park = parks.get(req.park_id, None)
    lat = park.centroid_lat if park else 41.04
    irrigated_area = park.total_irrigated_area_m2() if park else 120000.0

    try:
        weather_df = prepare_season_weather(
            season_year=req.season,
            latitude_deg=lat,
            source=req.source,
            park_id=req.park_id,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    sim_df, metrics = simulate_strategy_season(strat, weather_df)
    metrics.total_water_m3 = (metrics.total_water_mm / 1000.0) * irrigated_area

    # Günlük kayıtları sözlük listesine çevir
    daily_records = []
    for idx, row in sim_df.iterrows():
        rec = row.to_dict()
        rec["time"] = str(idx)
        daily_records.append(rec)

    return SimulateResponse(
        park_id=req.park_id,
        season=req.season,
        strategy=req.strategy,
        source=weather_df.attrs.get("source", "unknown"),
        metrics=metrics.to_dict(),
        daily_records=daily_records,
    )


@app.post("/compare", response_model=CompareResponse, dependencies=[Depends(verify_token)])
def post_compare(req: CompareRequest):
    """Birden çok sulama stratejisini koşturur ve CRITIC yöntemiyle sıralar."""
    try:
        ranked_df, _ = compare_all_strategies(
            season_year=req.season,
            park_id=req.park_id,
            source=req.source,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    weights = ranked_df.attrs.get("critic_weights", {})

    return CompareResponse(
        park_id=req.park_id,
        season=req.season,
        source=ranked_df.attrs.get("weather_source", "unknown"),
        critic_weights=weights,
        ranked_strategies=ranked_df.to_dict(orient="records"),
    )


@app.post("/sensitivity", response_model=SensitivityResponse, dependencies=[Depends(verify_token)])
def post_sensitivity(req: SensitivityRequest):
    """OAT veya Sobol parametre duyarlılık analizini koşturur."""
    try:
        weather_df = prepare_season_weather(
            season_year=req.season,
            source=req.source,
            park_id=req.park_id,
        ).iloc[:60]  # Performans için 60 gün
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if req.method.lower() == "oat":
        res_df = run_oat_sensitivity(weather_df)
    else:
        res_df = run_sobol_morris_sampling(weather_df, num_samples=25)

    return SensitivityResponse(
        method=req.method,
        source=weather_df.attrs.get("source", "unknown"),
        results=res_df.to_dict(orient="records"),
    )


@app.get("/testbed/state", response_model=TestbedStateResponse, dependencies=[Depends(verify_token)])
def get_testbed_state():
    """Testbed dijital ikiz durum kestirimi."""
    now_str = datetime.now(timezone.utc).isoformat()
    return TestbedStateResponse(
        node="node01",
        last_seen=now_str,
        soil_raw=540,
        soil_vwc_measured=0.245,
        depletion_estimated_mm=10.5,
        ks_estimated=1.0,
        last_command="STOP",
        source="synthetic",
    )


@app.get("/testbed/advice", response_model=TestbedAdviceResponse, dependencies=[Depends(verify_token)])
def get_testbed_advice():
    """Önerilen sulama süresi ve onay isteği."""
    return TestbedAdviceResponse(
        node="node01",
        recommended_duration_s=15,
        reason="Kök bölgesi nemi tarla kapasitesinin %70 altına indi; 15 sn kontrollü sulama tavsiye edilir.",
        requires_approval=True,
        source="synthetic",
    )


def export_openapi_json(output_path: Optional[Path | str] = None) -> Path:
    """OpenAPI JSON şemasını otomatik üretip diske yazar."""
    p = (
        Path(output_path)
        if output_path
        else Path(__file__).resolve().parent.parent.parent.parent / "docs" / "openapi.json"
    )
    p.parent.mkdir(parents=True, exist_ok=True)
    schema = app.openapi()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    return p
