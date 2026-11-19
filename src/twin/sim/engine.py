"""Simülasyon motoru: Sezonluk simülasyon koşturucu ve strateji karşılaştırıcı.

Kapsam:
- 2015-2025 sulama sezonları (Nisan - Ekim) yeniden kurgusu
- 5 sulama stratejisi (S0-S4) simülasyonu
- CRITIC çok kriterli sıralama entegrasyonu
- Sensör belirsizliği ve arıza enjeksiyon desteği
"""

import warnings
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from twin.config import TwinConfig
from twin.data.era5 import (
    aggregate_hourly_to_daily,
    generate_synthetic_era5,
    load_era5_season,
)
from twin.data.parks import Park, load_parks
from twin.model.et0 import fao56_penman_monteith_daily
from twin.model.kc import get_stage_based_kc
from twin.model.waterbalance import (
    compute_raw,
    compute_taw,
    depletion_to_vwc,
    simulate_water_balance_step,
)
from twin.sim.critic import rank_strategies_critic
from twin.sim.fault_injection import FaultConfig, inject_sensor_faults
from twin.sim.metrics import SimulationMetrics, calculate_simulation_metrics
from twin.sim.strategies import IrrigationStrategy, get_all_strategies


def prepare_season_weather(
    season_year: int = 2024,
    latitude_deg: float = 41.04,
    source: str = "auto",
    park_id: str = "yildiz",
    raw_dir: Optional[str] = None,
    processed_dir: Optional[str] = None,
) -> pd.DataFrame:
    """Belirtilen yılın Nisan - Ekim (1 Nisan - 31 Ekim) sezonu için günlük hava verisi hazırlar.

    Parametreler:
        season_year: Sezon yılı (2015-2025).
        latitude_deg: Enlem derecesi (ETo hesabı için).
        source: 'auto' (varsayılan), 'era5' veya 'synthetic'.
            'auto': data/processed/era5_{park}_{yıl}.csv varsa gerçek ERA5-Land verisini okur;
            yoksa UserWarning verip sentetik veriye düşer. Çözümlenen kaynak her zaman
            df.attrs["source"] içindedir ('era5' veya 'synthetic').
            'era5': gerçek veri zorunlu; yoksa FileNotFoundError.
        park_id: 'yildiz' veya 'macka'.
        raw_dir: Ham ERA5 NetCDF dosyaları dizini.
        processed_dir: İşlenmiş CSV dizini.
    """
    if source == "auto":
        p_dir = processed_dir or "data/processed"
        csv_file = Path(p_dir) / f"era5_{park_id}_{season_year}.csv"
        if csv_file.is_file():
            source = "era5"
        else:
            warnings.warn(
                f"Gerçek ERA5 dosyası bulunamadı ({csv_file}); "
                f"sezon {season_year} için SENTETİK hava kullanılıyor (source='synthetic').",
                UserWarning,
                stacklevel=2,
            )
            source = "synthetic"

    if source == "era5":
        r_dir = raw_dir or "data/raw/era5"
        p_dir = processed_dir or "data/processed"
        daily_df = load_era5_season(
            season_year=season_year,
            park_id=park_id,
            raw_dir=r_dir,
            processed_dir=p_dir,
        )
        daily_df.attrs["source"] = "era5"
        daily_df.attrs["park_id"] = park_id
        return daily_df

    if source != "synthetic":
        raise ValueError(f"Geçersiz veri kaynağı: '{source}'. Seçenekler: 'auto', 'era5', 'synthetic'.")

    start_str = f"{season_year}-04-01"
    end_str = f"{season_year}-10-31 23:00"

    hourly_df = generate_synthetic_era5(start_str, end_str, seed=season_year, lat=latitude_deg)
    daily_df = aggregate_hourly_to_daily(hourly_df)

    doy = daily_df.index.dayofyear.values
    eto_vals = fao56_penman_monteith_daily(
        temp_mean_c=daily_df["temp_mean"].values,
        temp_max_c=daily_df["temp_max"].values,
        temp_min_c=daily_df["temp_min"].values,
        wind_speed_2m_ms=daily_df["wind_speed_2m_ms"].values,
        rad_mj_m2_day=daily_df["rad_mj_m2"].values,
        rh_mean_pct=daily_df["rh_mean"].values,
        day_of_year=doy,
        latitude_deg=latitude_deg,
    )
    daily_df["eto_mm"] = eto_vals
    daily_df.attrs["source"] = "synthetic"
    daily_df.attrs["park_id"] = park_id
    return daily_df


def simulate_strategy_season(
    strategy: IrrigationStrategy,
    weather_df: pd.DataFrame,
    config: Optional[TwinConfig] = None,
    fault_config: Optional[FaultConfig] = None,
    initial_dr_mm: float = 0.0,
    forecast_rain_noise_std: float = 1.0,
    seed: int = 42,
) -> Tuple[pd.DataFrame, SimulationMetrics]:
    """Bir sulama stratejisini verilen sezon boyunca adım adım simüle eder.

    `seed`: sensör ölçüm gürültüsü ve yağış tahmini gürültüsü için rastgele tohum.
    """
    cfg = config or TwinConfig()
    theta_fc = float(cfg.soil.theta_fc.value)
    theta_wp = float(cfg.soil.theta_wp.value)
    zr = float(cfg.soil.root_depth_m.value)
    p = float(cfg.soil.p_depletion.value)
    eff = float(cfg.irrigation.efficiency.value)
    runoff_thresh = float(cfg.soil.runoff_threshold_mm.value)

    taw = compute_taw(theta_fc, theta_wp, zr)
    raw = compute_raw(taw, p)

    n = len(weather_df)
    dates = weather_df.index
    rng = np.random.default_rng(seed)

    # Arıza enjeksiyonu uygulanacaksa sensör ölçüm serisini üret
    f_cfg = fault_config or FaultConfig(fault_type="none")

    dr_curr = initial_dr_mm

    records = []

    for i in range(n):
        curr_date = dates[i]
        w_row = weather_df.iloc[i].copy()
        eto = float(w_row["eto_mm"])
        rain = float(w_row["rain_mm"])
        month = curr_date.month

        kc = get_stage_based_kc(month, crop_params=cfg.crop)
        w_row["kc"] = kc

        # 24 saatlik yağış tahmini (gerçek yağış + bilinen büyüklükte tahmin gürültüsü)
        rain_24h_ahead = float(weather_df["rain_mm"].iloc[i + 1]) if i + 1 < n else 0.0
        forecast_rain = max(0.0, rain_24h_ahead + rng.normal(0, forecast_rain_noise_std))

        # Güncel gerçek nem
        true_theta = depletion_to_vwc(dr_curr, theta_fc, zr)

        # Sensör okuması (arıza modeli uygulanmış veya standart ölçüm gürültüsü)
        if f_cfg.fault_type != "none":
            s_series = pd.Series([true_theta], index=[curr_date])
            sensor_obs = float(inject_sensor_faults(s_series, f_cfg, seed=i).iloc[0])
        else:
            obs_noise = float(cfg.assimilation.obs_error_std.value)
            sensor_obs = true_theta + rng.normal(0, obs_noise)

        # Strateji sulama kararı verir
        irr_dose_mm = strategy.decide(
            day_idx=i,
            current_date=curr_date,
            weather_row=w_row,
            state_depletion_mm=dr_curr,
            sensor_theta_obs=sensor_obs,
            forecast_rain_24h_mm=forecast_rain,
            config=cfg,
        )

        # Fiziksel su dengesi adımı
        state = simulate_water_balance_step(
            dr_prev_mm=dr_curr,
            eto_mm=eto,
            kc=kc,
            precip_mm=rain,
            irrigation_mm=irr_dose_mm,
            theta_fc=theta_fc,
            theta_wp=theta_wp,
            root_depth_m=zr,
            p_depletion=p,
            irr_efficiency=eff,
            runoff_thresh_mm=runoff_thresh,
        )

        dr_curr = state.depletion_mm

        records.append(
            {
                "time": curr_date,
                "eto_mm": eto,
                "kc": kc,
                "rain_mm": rain,
                "forecast_rain_mm": forecast_rain,
                "irrigation_gross_mm": irr_dose_mm,
                "irrigation_net_mm": irr_dose_mm * eff,
                "depletion_mm": state.depletion_mm,
                "theta_vwc": state.theta_vwc,
                "sensor_obs": sensor_obs,
                "ks": state.ks,
                "eta_mm": state.eta_mm,
                "dp_mm": state.dp_mm,
                "ro_mm": state.ro_mm,
                "taw_mm": taw,
                "raw_mm": raw,
            }
        )

    sim_df = pd.DataFrame(records).set_index("time")
    metrics = calculate_simulation_metrics(sim_df, strategy.name)
    return sim_df, metrics


def compare_all_strategies(
    season_year: int = 2024,
    park_id: str = "yildiz",
    config: Optional[TwinConfig] = None,
    fault_config: Optional[FaultConfig] = None,
    source: str = "auto",
) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
    """Tüm 5 stratejiyi (S0-S4) koşturur, metrikleri hesaplar ve CRITIC ile sıralar."""
    parks = load_parks()
    park = parks.get(park_id, Park(park_id, park_id.upper(), 200000.0, 29.0, 41.0))
    irrigated_area = park.total_irrigated_area_m2()

    weather_df = prepare_season_weather(
        season_year,
        latitude_deg=park.centroid_lat,
        source=source,
        park_id=park_id,
    )
    strategies = get_all_strategies()

    all_metrics = []
    sim_dfs: Dict[str, pd.DataFrame] = {}

    for name, strat in strategies.items():
        sim_df, m = simulate_strategy_season(
            strategy=strat,
            weather_df=weather_df,
            config=config,
            fault_config=fault_config,
        )
        m.total_water_m3 = (m.total_water_mm / 1000.0) * irrigated_area
        sim_dfs[name] = sim_df
        all_metrics.append(m.to_dict())

    df_metrics = pd.DataFrame(all_metrics)
    ranked_df = rank_strategies_critic(df_metrics)
    ranked_df.attrs["weather_source"] = weather_df.attrs.get("source", "unknown")

    return ranked_df, sim_dfs
