"""Parametre duyarlılık analizi modülü (OAT ve Küresel Duyarlılık - RQ3).

Analiz edilen parametreler:
1. Bitki katsayısı (Kc)
2. Etkili kök derinliği (Zr)
3. Tarla kapasitesi (theta_fc)
4. Solma noktası (theta_wp)
5. Kritik tükenme kesri (p)

Yöntemler:
- OAT (One-At-a-Time): Tekil parametre pertürbasyonu ve elastikiyet/etki hesabı
- Morris / Sobol Örneklemesi: Çok boyutlu parametre uzayı taraması
"""

import copy
from typing import List, Optional

import numpy as np
import pandas as pd

from twin.config import TwinConfig
from twin.model.waterbalance import run_water_balance_simulation
from twin.sim.metrics import calculate_simulation_metrics


def run_oat_sensitivity(
    weather_df: pd.DataFrame,
    base_config: Optional[TwinConfig] = None,
    perturbation_pct: float = 0.20,  # +/- %20 değişim
    param_keys: List[str] = ["kc_mid", "root_depth_m", "theta_fc", "theta_wp", "p_depletion"],
) -> pd.DataFrame:
    """One-At-a-Time (OAT) yerel duyarlılık analizini koşturur."""
    cfg = base_config or TwinConfig()

    results = []

    # Temel durum simülasyonu
    base_kc = float(cfg.crop.kc_mid.value)
    sim_base = run_water_balance_simulation(weather_df, kc_series=base_kc, config=cfg)
    m_base = calculate_simulation_metrics(sim_base, "Baseline")

    for param in param_keys:
        for factor in [1.0 - perturbation_pct, 1.0 + perturbation_pct]:
            cfg_pert = copy.deepcopy(cfg)
            kc_val = base_kc

            if param == "kc_mid":
                kc_val = base_kc * factor
            elif param == "root_depth_m":
                cfg_pert.soil.root_depth_m.value = float(cfg.soil.root_depth_m.value) * factor
            elif param == "theta_fc":
                cfg_pert.soil.theta_fc.value = float(cfg.soil.theta_fc.value) * factor
            elif param == "theta_wp":
                cfg_pert.soil.theta_wp.value = float(cfg.soil.theta_wp.value) * factor
            elif param == "p_depletion":
                cfg_pert.soil.p_depletion.value = float(
                    np.clip(float(cfg.soil.p_depletion.value) * factor, 0.1, 0.9)
                )

            sim_pert = run_water_balance_simulation(weather_df, kc_series=kc_val, config=cfg_pert)
            m_pert = calculate_simulation_metrics(sim_pert, f"{param}_{factor:.2f}")

            # Değişim yüzdeleri
            water_change_pct = (
                (m_pert.total_water_mm - m_base.total_water_mm) / (m_base.total_water_mm + 1e-4)
            ) * 100.0
            stress_change = m_pert.cumulative_stress - m_base.cumulative_stress

            results.append(
                {
                    "parameter": param,
                    "factor": round(factor, 2),
                    "total_water_mm": m_pert.total_water_mm,
                    "water_change_pct": round(water_change_pct, 2),
                    "stress_days": m_pert.stress_days_count,
                    "cumulative_stress": round(m_pert.cumulative_stress, 2),
                    "stress_diff": round(stress_change, 2),
                }
            )

    return pd.DataFrame(results)


def run_sobol_morris_sampling(
    weather_df: pd.DataFrame,
    num_samples: int = 100,
    seed: int = 42,
) -> pd.DataFrame:
    """Parametre uzayında Monte Carlo / Sobol tarzı küresel duyarlılık taraması yapar."""
    rng = np.random.default_rng(seed)

    # Parametre dağılım aralıkları (FAO-56 aralıkları)
    kc_samples = rng.uniform(0.70, 1.15, num_samples)
    zr_samples = rng.uniform(0.20, 0.45, num_samples)
    fc_samples = rng.uniform(0.22, 0.35, num_samples)
    wp_samples = rng.uniform(0.10, 0.18, num_samples)
    p_samples = rng.uniform(0.35, 0.65, num_samples)

    records = []
    for i in range(num_samples):
        cfg = TwinConfig()
        cfg.soil.root_depth_m.value = float(zr_samples[i])
        cfg.soil.theta_fc.value = float(fc_samples[i])
        cfg.soil.theta_wp.value = float(wp_samples[i])
        cfg.soil.p_depletion.value = float(p_samples[i])

        sim_df = run_water_balance_simulation(weather_df, kc_series=float(kc_samples[i]), config=cfg)
        metrics = calculate_simulation_metrics(sim_df, f"Sample_{i}")

        records.append(
            {
                "kc": kc_samples[i],
                "root_depth_m": zr_samples[i],
                "theta_fc": fc_samples[i],
                "theta_wp": wp_samples[i],
                "p_depletion": p_samples[i],
                "total_water_mm": metrics.total_water_mm,
                "cumulative_stress": metrics.cumulative_stress,
                "stress_days": metrics.stress_days_count,
            }
        )

    return pd.DataFrame(records)
