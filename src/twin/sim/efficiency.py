"""Su kullanım verimliliği: teorik alt sınır (kâhin) ve kütle dengesi ayrıştırması.

Kapsam:
- `OracleJustInTime`: tam bilgi altında "tam zamanında" sulama. Gün sonu tükenmesini hedef
  eşiğin (D <= RAW) üstüne çıkarmayacak en küçük dozu verir. Gerçek bir strateji DEĞİLDİR
  (o günün ETo ve yağışını önceden bilir); tüm stratejiler için kıyas tabanıdır.
- `minimum_irrigation_lp`: aynı problemin doğrusal programlama gevşetmesi. LP en iyi değeri,
  stressiz sezon için gereken net sulamanın alt sınırıdır. JIT toplamı LP değerine eşitse
  JIT'in optimal olduğu o sezon için sayısal olarak sertifikalanmış olur
  (ispat: docs/model/VERIMLILIK_MODELI.md, Önerme 1).
- `water_balance_accounting`: sezonluk su bütçesi ve kapanış hatası.
- `decompose_excess`: bir stratejinin referansa göre fazla suyunu ETa, derin sızma ve
  depolama terimlerine ayırır.

Varsayımlar: FAO-56 kök bölgesi kovası (model/waterbalance.py), sabit uygulama verimi,
yüzey akışı yalnız yağışa bağlı (dışsal), Kc ve ETo dışsal.
"""

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import linprog

from twin.config import TwinConfig
from twin.model.kc import get_stage_based_kc
from twin.model.waterbalance import compute_ks, compute_raw, compute_taw
from twin.sim.strategies import IrrigationStrategy


def _runoff(precip_mm: np.ndarray, runoff_thresh_mm: float) -> np.ndarray:
    """model/waterbalance.py ile aynı yüzey akışı kuralı: RO = max(0, P - eşik)."""
    return np.maximum(0.0, precip_mm - runoff_thresh_mm)


class OracleJustInTime(IrrigationStrategy):
    """Kâhin tam zamanında sulama (tam bilgi, kıyas tabanı).

    Hedef: Dr_t <= D her gün sonunda (D = target_fraction_of_raw * RAW). Ks yalnız önceki günün
    tükenmesine bağlı olduğundan bu, sezon boyunca Ks = 1 (stressiz) demektir.
    """

    def __init__(self, target_fraction_of_raw: float = 1.0):
        if not 0.0 < target_fraction_of_raw <= 1.0:
            raise ValueError("target_fraction_of_raw (0, 1] aralığında olmalı.")
        self.name = "ORACLE_JIT"
        self.target_frac = target_fraction_of_raw

    def decide(
        self,
        day_idx: int,
        current_date: pd.Timestamp,
        weather_row: pd.Series,
        state_depletion_mm: float,
        sensor_theta_obs: Optional[float],
        forecast_rain_24h_mm: float,
        config: TwinConfig,
    ) -> float:
        theta_fc = float(config.soil.theta_fc.value)
        theta_wp = float(config.soil.theta_wp.value)
        zr = float(config.soil.root_depth_m.value)
        p = float(config.soil.p_depletion.value)
        eff = float(config.irrigation.efficiency.value)
        cap = float(config.irrigation.max_gross_dose_mm.value)
        runoff_thresh = float(config.soil.runoff_threshold_mm.value)

        taw = compute_taw(theta_fc, theta_wp, zr)
        raw = compute_raw(taw, p)
        target = self.target_frac * raw

        rain = float(weather_row["rain_mm"])
        p_net = rain - max(0.0, rain - runoff_thresh)
        ks = compute_ks(state_depletion_mm, taw, raw, p)
        eta = ks * float(weather_row["kc"]) * float(weather_row["eto_mm"])

        dr_no_irr = state_depletion_mm - p_net + eta
        if dr_no_irr <= target:
            return 0.0
        return float(min((dr_no_irr - target) / eff, cap))


@dataclass
class LowerBoundResult:
    """LP alt sınır sonucu."""

    total_net_mm: float
    total_gross_mm: float
    daily_net_mm: np.ndarray
    depletion_mm: np.ndarray
    status: str


def minimum_irrigation_lp(
    weather_df: pd.DataFrame,
    config: Optional[TwinConfig] = None,
    target_fraction_of_raw: float = 1.0,
    initial_dr_mm: float = 0.0,
) -> LowerBoundResult:
    """Stressiz sezon için gereken en az sulamayı doğrusal programlama ile hesaplar.

    Karar değişkenleri (t = 1..n): net sulama i_t, drenaj d_t, gün sonu tükenme x_t.
        min  sum_t i_t
        s.t. x_t = x_{t-1} + Kc_t*ETo_t - (P_t - RO_t) - i_t + d_t
             0 <= x_t <= D,  i_t >= 0,  i_t <= eta*cap,  d_t >= 0
    Fiziksel modelde d_t yalnız x_t = 0 iken pozitif olabilir; LP bunu zorlamaz (gevşetme),
    bu yüzden LP değeri gerçek modeldeki her stressiz politikanın alt sınırıdır.
    """
    cfg = config or TwinConfig()
    theta_fc = float(cfg.soil.theta_fc.value)
    theta_wp = float(cfg.soil.theta_wp.value)
    zr = float(cfg.soil.root_depth_m.value)
    p = float(cfg.soil.p_depletion.value)
    eff = float(cfg.irrigation.efficiency.value)
    cap = float(cfg.irrigation.max_gross_dose_mm.value)
    runoff_thresh = float(cfg.soil.runoff_threshold_mm.value)

    target = target_fraction_of_raw * compute_raw(compute_taw(theta_fc, theta_wp, zr), p)

    rain = weather_df["rain_mm"].to_numpy(dtype=float)
    eto = weather_df["eto_mm"].to_numpy(dtype=float)
    if "kc" in weather_df.columns:
        kc = weather_df["kc"].to_numpy(dtype=float)
    else:
        kc = np.array([get_stage_based_kc(d.month, crop_params=cfg.crop) for d in weather_df.index])

    n = len(weather_df)
    a = kc * eto - (rain - _runoff(rain, runoff_thresh))

    # Değişken sırası: [i_1..i_n, d_1..d_n, x_1..x_n]
    eye = sparse.identity(n, format="csr")
    shift = sparse.diags(np.ones(n - 1), -1, shape=(n, n), format="csr")
    a_eq = sparse.hstack([eye, -eye, eye - shift], format="csr")
    b_eq = a.copy()
    b_eq[0] += initial_dr_mm

    cost = np.concatenate([np.ones(n), np.zeros(2 * n)])
    bounds = [(0.0, eff * cap)] * n + [(0.0, None)] * n + [(0.0, target)] * n

    res = linprog(cost, A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs")
    if not res.success:
        return LowerBoundResult(np.nan, np.nan, np.full(n, np.nan), np.full(n, np.nan), res.message)

    i_net = res.x[:n]
    return LowerBoundResult(
        total_net_mm=float(i_net.sum()),
        total_gross_mm=float(i_net.sum() / eff),
        daily_net_mm=i_net,
        depletion_mm=res.x[2 * n :],
        status=res.message,
    )


def water_balance_accounting(
    sim_df: pd.DataFrame,
    initial_dr_mm: float = 0.0,
) -> Dict[str, float]:
    """Sezonluk su bütçesi [mm] ve türetilmiş verimlilik oranları.

    Kapanış: (P - RO) + I_net - ETa - DP - (Dr_0 - Dr_n) = 0 olmalı.
    """
    p = float(sim_df["rain_mm"].sum())
    ro = float(sim_df["ro_mm"].sum())
    i_gross = float(sim_df["irrigation_gross_mm"].sum())
    i_net = float(sim_df["irrigation_net_mm"].sum())
    eta = float(sim_df["eta_mm"].sum())
    etc = float((sim_df["kc"] * sim_df["eto_mm"]).sum())
    dp = float(sim_df["dp_mm"].sum())
    dr_end = float(sim_df["depletion_mm"].iloc[-1])
    storage_gain = initial_dr_mm - dr_end

    closure = (p - ro) + i_net - eta - dp - storage_gain
    total_input = p + i_gross

    return {
        "rain_mm": p,
        "runoff_mm": ro,
        "irrigation_gross_mm": i_gross,
        "irrigation_net_mm": i_net,
        "application_loss_mm": i_gross - i_net,
        "etc_mm": etc,
        "eta_mm": eta,
        "deep_percolation_mm": dp,
        "storage_gain_mm": storage_gain,
        "closure_error_mm": closure,
        # 1 - sum(ETa)/sum(ETc): bitki su açığı (0 = stressiz)
        "relative_et_deficit": 1.0 - eta / etc if etc > 0 else 0.0,
        # Toplam su girdisinin (yağış + brüt sulama) bitki tüketimine giden payı
        "consumptive_fraction": eta / total_input if total_input > 0 else 0.0,
    }


def decompose_excess(
    sim_df: pd.DataFrame,
    reference_df: pd.DataFrame,
    irr_efficiency: float,
) -> Dict[str, float]:
    """Bir stratejinin referansa göre fazla brüt suyunu terimlerine ayırır [mm].

    Aynı hava ve başlangıç durumunda kapanış denkleminden:
        dI_net = dETa + dDP - d(Dr_0 - Dr_n)   =>   dI_gross = dI_net / eta_irr
    Stressiz iki politikada dETa = 0 olduğundan fazla su = fazla derin sızma + depolama farkı.
    """
    s = water_balance_accounting(sim_df)
    r = water_balance_accounting(reference_df)
    d_eta = s["eta_mm"] - r["eta_mm"]
    d_dp = s["deep_percolation_mm"] - r["deep_percolation_mm"]
    d_storage = s["storage_gain_mm"] - r["storage_gain_mm"]
    return {
        "excess_gross_mm": s["irrigation_gross_mm"] - r["irrigation_gross_mm"],
        "from_eta_mm": d_eta / irr_efficiency,
        "from_deep_percolation_mm": d_dp / irr_efficiency,
        "from_storage_mm": d_storage / irr_efficiency,
    }


def season_efficiency_table(
    weather_df: pd.DataFrame,
    config: Optional[TwinConfig] = None,
    strategies: Optional[Dict[str, IrrigationStrategy]] = None,
) -> pd.DataFrame:
    """Bir sezon için tüm stratejileri kâhin alt sınırına ve S0'a göre tablolaştırır.

    Sütunlar (mm, brüt): toplam sulama, kâhine göre fazla su ve ayrıştırması, S0'a göre tasarruf,
    stres göstergeleri. `source` sütunu hava verisinin kaynağıdır (era5 / synthetic).
    """
    from twin.sim.engine import simulate_strategy_season
    from twin.sim.strategies import get_all_strategies

    cfg = config or TwinConfig()
    eff = float(cfg.irrigation.efficiency.value)
    strats = dict(strategies or get_all_strategies())

    oracle_df, _ = simulate_strategy_season(OracleJustInTime(), weather_df, config=cfg)
    lp = minimum_irrigation_lp(oracle_df, cfg)
    w_star = float(oracle_df["irrigation_gross_mm"].sum())

    runs = {"ORACLE": oracle_df}
    for key, strat in strats.items():
        runs[key], _ = simulate_strategy_season(strat, weather_df, config=cfg)
    w_s0 = float(runs["S0"]["irrigation_gross_mm"].sum()) if "S0" in runs else np.nan

    rows = []
    for key, df in runs.items():
        acc = water_balance_accounting(df)
        dec = decompose_excess(df, oracle_df, eff)
        w = acc["irrigation_gross_mm"]
        rows.append(
            {
                "strategy": key,
                "irrigation_gross_mm": w,
                "excess_vs_oracle_mm": dec["excess_gross_mm"],
                "excess_from_eta_mm": dec["from_eta_mm"],
                "excess_from_dp_mm": dec["from_deep_percolation_mm"],
                "excess_from_storage_mm": dec["from_storage_mm"],
                "saving_vs_s0_pct": 100.0 * (w_s0 - w) / w_s0 if w_s0 > 0 else np.nan,
                "stress_days": int((df["ks"] < 0.999).sum()),
                "cumulative_stress": float((1.0 - df["ks"]).clip(lower=0.0).sum()),
                "relative_et_deficit": acc["relative_et_deficit"],
                "deep_percolation_mm": acc["deep_percolation_mm"],
                "consumptive_fraction": acc["consumptive_fraction"],
                "max_daily_gross_mm": float(df["irrigation_gross_mm"].max()),
                "closure_error_mm": acc["closure_error_mm"],
            }
        )
    out = pd.DataFrame(rows)
    out["lp_lower_bound_gross_mm"] = lp.total_gross_mm
    out["oracle_lp_gap_mm"] = w_star - lp.total_gross_mm
    out["source"] = weather_df.attrs.get("source", "unknown")
    return out


def allowed_depletion_sweep(
    weather_df: pd.DataFrame,
    config: Optional[TwinConfig] = None,
    fractions: tuple = (0.25, 0.5, 0.75, 1.0),
) -> pd.DataFrame:
    """İzin verilen tükenme eşiğine (D = f * RAW) göre stressiz en az brüt su [mm]."""
    from twin.sim.engine import simulate_strategy_season

    cfg = config or TwinConfig()
    rows = []
    for f in fractions:
        df, _ = simulate_strategy_season(OracleJustInTime(f), weather_df, config=cfg)
        acc = water_balance_accounting(df)
        rows.append(
            {
                "fraction_of_raw": f,
                "min_gross_mm": acc["irrigation_gross_mm"],
                "deep_percolation_mm": acc["deep_percolation_mm"],
                "lp_gross_mm": minimum_irrigation_lp(df, cfg, target_fraction_of_raw=f).total_gross_mm,
            }
        )
    out = pd.DataFrame(rows)
    out["source"] = weather_df.attrs.get("source", "unknown")
    return out


def park_zone_requirement(
    weather_df: pd.DataFrame,
    zones: list,
    base_config: Optional[TwinConfig] = None,
) -> pd.DataFrame:
    """Park zonlarının bitki tipine göre stressiz en az brüt suyu [mm] ve hacmi [m3].

    `zones`: parks.IrrigationZone listesi. Zon tipi ZONE_VEG_TYPE_TO_PROFILE ile doğrulanmış
    bir profile eşlenir; profili olmayan zon hesaplanmaz, `status` sütununda belirtilir
    (uydurma katsayıyla doldurulmaz). Hacim = mm / 1000 * alan.
    """
    from twin.config import ZONE_VEG_TYPE_TO_PROFILE, config_for_vegetation
    from twin.sim.engine import simulate_strategy_season

    rows = []
    for z in zones:
        profile = ZONE_VEG_TYPE_TO_PROFILE.get(z.veg_type)
        row = {"zone_id": z.zone_id, "veg_type": z.veg_type, "profile": profile, "area_m2": z.area_m2}
        if profile is None:
            row.update(min_gross_mm=np.nan, min_gross_m3=np.nan, status="no_verified_profile")
        else:
            cfg = config_for_vegetation(profile, base_config)
            df, _ = simulate_strategy_season(OracleJustInTime(), weather_df, config=cfg)
            w = float(df["irrigation_gross_mm"].sum())
            row.update(min_gross_mm=w, min_gross_m3=w / 1000.0 * z.area_m2, status="ok")
        rows.append(row)
    out = pd.DataFrame(rows)
    out["source"] = weather_df.attrs.get("source", "unknown")
    return out
