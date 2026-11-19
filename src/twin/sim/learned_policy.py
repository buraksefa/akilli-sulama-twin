"""Öğrenilmiş sulama politikası: kâhin JIT'in nedensel (uygulanabilir) taklidi.

Kâhin (`OracleJustInTime`) o günün ETo ve yağışını bilir; gerçekte uygulanamaz. Buradaki
politikalar karar anında yalnız bilinebilecek bilgiyi kullanır:
- önceki günlerin gerçekleşmiş ETo ve yağışı (bugünün değeri DEĞİL),
- kök bölgesi tükenmesi Dr_{t-1} (S2 ile aynı bilgi; sensörlü sürüm ayrı iş),
- takvim (gün-yıl, aya bağlı Kc).

İki politika:
- `PersistenceJIT` (öğrenmesiz taban): bugünün ETc'si dünkü ile aynı, yağış yok varsayımıyla JIT.
- `LearnedPolicy` (S6): kâhin dozunu nedensel özelliklerden tahmin eden gradyan artırmalı
  regresyon; DAgger ile eğitilir (öğrenilen politikanın ziyaret ettiği durumlar kâhinle
  etiketlenir, dağılım kayması azaltılır). DAgger: Ross, Gordon & Bagnell (2011), AISTATS
  (bellekten, doğrulanmadı).

Değerlendirme yıl-dışı-bırak (leave-one-year-out) ile yapılır: test yılı eğitime hiç girmez.
"""

from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from twin.config import TwinConfig
from twin.model.assimilation import EnsembleKalmanFilter
from twin.model.waterbalance import (
    compute_raw,
    compute_taw,
    simulate_water_balance_step,
    vwc_to_depletion,
)
from twin.sim.efficiency import OracleJustInTime
from twin.sim.strategies import IrrigationStrategy

FEATURES = [
    "dr_prev_mm",
    "eto_lag1",
    "eto_mean3",
    "eto_mean7",
    "rain_lag1",
    "rain_sum3",
    "kc",
    "doy_sin",
    "doy_cos",
]


class _History:
    """Geçmiş günlerin gerçekleşmiş hava kaydı (yalnız dünden geriye)."""

    def __init__(self):
        self.eto: List[float] = []
        self.rain: List[float] = []

    def features(self, dr_prev_mm: float, kc: float, date: pd.Timestamp) -> Dict[str, float]:
        eto = np.array(self.eto) if self.eto else np.array([np.nan])
        rain = np.array(self.rain) if self.rain else np.array([np.nan])
        doy = 2.0 * np.pi * date.dayofyear / 365.25
        return {
            "dr_prev_mm": dr_prev_mm,
            "eto_lag1": float(eto[-1]),
            "eto_mean3": float(np.mean(eto[-3:])),
            "eto_mean7": float(np.mean(eto[-7:])),
            "rain_lag1": float(rain[-1]),
            "rain_sum3": float(np.sum(rain[-3:])),
            "kc": kc,
            "doy_sin": float(np.sin(doy)),
            "doy_cos": float(np.cos(doy)),
        }

    def push(self, weather_row: pd.Series) -> None:
        self.eto.append(float(weather_row["eto_mm"]))
        self.rain.append(float(weather_row["rain_mm"]))


class _CausalStrategy(IrrigationStrategy):
    """Geçmişi kendisi tutan, bugünün hava değerine bakmayan strateji tabanı."""

    def __init__(self):
        self._hist = _History()

    def _features(self, day_idx, current_date, weather_row, state_depletion_mm) -> Dict[str, float]:
        if day_idx == 0:
            self._hist = _History()
        return self._hist.features(state_depletion_mm, float(weather_row["kc"]), current_date)

    def _finish_day(self, weather_row: pd.Series) -> None:
        # Gün kapandıktan sonra gerçekleşen değer geçmişe eklenir; bir sonraki gün kullanılır.
        self._hist.push(weather_row)


class PersistenceJIT(_CausalStrategy):
    """Öğrenmesiz taban: ETc_t ≈ Kc_t · ETo_{t-1}, yağış = 0 varsayımıyla tam zamanında doz.

    Hedef tükenme D = target_fraction_of_raw · RAW (1.0 = sınırda; < 1 güvenlik payı).
    """

    def __init__(self, target_fraction_of_raw: float = 1.0):
        super().__init__()
        self.name = "S5_PersistenceJIT"
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
        f = self._features(day_idx, current_date, weather_row, state_depletion_mm)
        self._finish_day(weather_row)
        if np.isnan(f["eto_lag1"]):
            return 0.0
        raw = compute_raw(
            compute_taw(
                config.soil.theta_fc.value, config.soil.theta_wp.value, config.soil.root_depth_m.value
            ),
            config.soil.p_depletion.value,
        )
        need = state_depletion_mm + f["kc"] * f["eto_lag1"] - self.target_frac * raw
        if need <= 0.0:
            return 0.0
        eff = float(config.irrigation.efficiency.value)
        return float(min(need / eff, float(config.irrigation.max_gross_dose_mm.value)))


class LearnedPolicy(_CausalStrategy):
    """S6: kâhin dozunu nedensel özelliklerden tahmin eden öğrenilmiş politika."""

    def __init__(self, model: HistGradientBoostingRegressor):
        super().__init__()
        self.name = "S6_LearnedPolicy"
        self.model = model

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
        f = self._features(day_idx, current_date, weather_row, state_depletion_mm)
        self._finish_day(weather_row)
        pred = float(self.model.predict(pd.DataFrame([f], columns=FEATURES))[0])
        return float(np.clip(pred, 0.0, float(config.irrigation.max_gross_dose_mm.value)))


class _Recorder(IrrigationStrategy):
    """Ziyaret edilen her durumda (özellik, kâhin dozu) kaydeder; eylemi `actor` seçer."""

    def __init__(self, actor: Optional[IrrigationStrategy], target_fraction_of_raw: float = 1.0):
        self.name = "recorder"
        self.actor = actor
        self.oracle = OracleJustInTime(target_fraction_of_raw)
        self.hist = _History()
        self.rows: List[Dict[str, float]] = []

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
        fc = forecast_rain_24h_mm
        if day_idx == 0:
            self.hist = _History()
        feats = self.hist.features(state_depletion_mm, float(weather_row["kc"]), current_date)
        label = self.oracle.decide(
            day_idx, current_date, weather_row, state_depletion_mm, sensor_theta_obs, fc, config
        )
        self.hist.push(weather_row)
        self.rows.append({**feats, "label_gross_mm": label})
        if self.actor is None:
            return label
        return self.actor.decide(
            day_idx, current_date, weather_row, state_depletion_mm, sensor_theta_obs, fc, config
        )


def _new_model(seed: int) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(random_state=seed, early_stopping=False)


def train_dagger(
    seasons: List[pd.DataFrame],
    config: Optional[TwinConfig] = None,
    iterations: int = 3,
    seed: int = 0,
    target_fraction_of_raw: float = 1.0,
) -> HistGradientBoostingRegressor:
    """DAgger: ilk tur kâhin yürür, sonraki turlarda öğrenilen politika yürür; tüm ziyaret
    edilen durumlar kâhinle etiketlenip veri kümesi büyütülür ve model yeniden eğitilir."""
    from twin.sim.engine import simulate_strategy_season

    cfg = config or TwinConfig()
    data: List[Dict[str, float]] = []
    model: Optional[HistGradientBoostingRegressor] = None
    for it in range(iterations + 1):
        for w in seasons:
            actor = None if model is None else LearnedPolicy(model)
            rec = _Recorder(actor, target_fraction_of_raw)
            simulate_strategy_season(rec, w, config=cfg)
            data.extend(rec.rows)
        df = pd.DataFrame(data)
        model = _new_model(seed)
        model.fit(df[FEATURES], df["label_gross_mm"])
    return model


def leave_one_year_out(
    seasons: Dict[int, pd.DataFrame],
    config: Optional[TwinConfig] = None,
    iterations: int = 3,
    seed: int = 0,
    target_fraction_of_raw: float = 1.0,
) -> pd.DataFrame:
    """Her yıl için diğer yıllarla eğit, o yılda test et; kâhin, S0-S4, S5 ve S6'yı tablola.

    S5 ve S6 aynı hedef tükenmeyle (target_fraction_of_raw · RAW) çalışır; kâhin satırı her
    zaman tam RAW hedefli alt sınırdır.
    """
    from twin.sim.efficiency import season_efficiency_table
    from twin.sim.strategies import get_all_strategies

    cfg = config or TwinConfig()
    tables = []
    for test_year, weather in seasons.items():
        train = [w for y, w in seasons.items() if y != test_year]
        model = train_dagger(train, cfg, iterations, seed, target_fraction_of_raw)
        strats = dict(get_all_strategies())
        strats["S5"] = PersistenceJIT(target_fraction_of_raw)
        strats["S6"] = LearnedPolicy(model)
        t = season_efficiency_table(weather, config=cfg, strategies=strats)
        t.insert(0, "season", test_year)
        t["train_years"] = ",".join(str(y) for y in seasons if y != test_year)
        t["dagger_iterations"] = iterations
        t["seed"] = seed
        t["target_fraction_of_raw"] = target_fraction_of_raw
        tables.append(t)
    return pd.concat(tables, ignore_index=True)


ESTIMATORS = ("true", "sensor", "openloop", "enkf")


class EstimatedPersistenceJIT(PersistenceJIT):
    """S5 + durum kestirimi: gerçek Dr yerine sabah kestirilen Dr̂_{t-1} ile karar.

    Kestiriciler (karar anında yalnız bilinebilecek bilgi):
    - "true": gerçek Dr_{t-1} (referans; S5 ile özdeş).
    - "sensor": yalnız sensör, Dr̂ = clip(vwc_to_depletion(θ_obs), 0, TAW).
    - "openloop": sensörsüz model; kendi Dr̂'sini dünkü (b·ETo, Kc, yağış) ve kendi dünkü
      dozuyla su dengesi adımıyla ilerletir; Dr̂_0 = 0 (sezon tarla kapasitesinde başlar).
    - "enkf": EnKF; önce DÜNKÜ hava ve dünkü dozla forecast_step, sonra bugünkü sensör
      gözlemiyle (Dr_{t-1}'i ölçer) analysis_step. Zamanlama nedenseldir.

    eto_bias_factor b: ikizin ETo'su = b × gerçek ETo (model hatası senaryosu; ör. ERA5 kıyı
    hücresi yanlılığı). Hem kestiricinin modeli hem doz formülü b·ETo kullanır.
    Doz = max(0, Dr̂ + Kc_t·b·ETo_{t-1} − D) / η, u_max ile sınırlı.
    Her gün (Dr̂_{t-1}, gerçek Dr_{t-1}) `est_log`a yazılır.
    """

    def __init__(
        self,
        estimator: str = "true",
        target_fraction_of_raw: float = 1.0,
        eto_bias_factor: float = 1.0,
        seed: int = 0,
    ):
        if estimator not in ESTIMATORS:
            raise ValueError(f"Bilinmeyen kestirici '{estimator}'. Seçenekler: {ESTIMATORS}")
        super().__init__(target_fraction_of_raw)
        self.name = f"S5_{estimator}"
        self.estimator = estimator
        self.bias = eto_bias_factor
        self.seed = seed
        self.est_log: List[tuple] = []

    def _reset(self, config: TwinConfig) -> None:
        self.est_log = []
        self._dr_ol = 0.0
        self._dr_hat = 0.0
        self._last_dose = 0.0
        self._prev_row: Optional[pd.Series] = None
        self._enkf = None
        if self.estimator == "enkf":
            self._enkf = EnsembleKalmanFilter(
                num_members=40,
                theta_fc=float(config.soil.theta_fc.value),
                theta_wp=float(config.soil.theta_wp.value),
                root_depth_m=float(config.soil.root_depth_m.value),
                p_depletion=float(config.soil.p_depletion.value),
                obs_error_std=float(config.assimilation.obs_error_std.value),
                proc_error_std_dr=float(config.assimilation.proc_error_std_dr.value),
                seed=self.seed,
            )

    def _estimate(self, state_depletion_mm: float, sensor_theta_obs: Optional[float], config: TwinConfig):
        soil = config.soil
        fc, wp, zr = float(soil.theta_fc.value), float(soil.theta_wp.value), float(soil.root_depth_m.value)
        eff = float(config.irrigation.efficiency.value)
        has_obs = sensor_theta_obs is not None and not np.isnan(sensor_theta_obs)
        prev = self._prev_row

        if self.estimator == "true":
            return state_depletion_mm
        if self.estimator == "sensor":
            if has_obs:
                self._dr_hat = float(
                    np.clip(vwc_to_depletion(sensor_theta_obs, fc, zr), 0.0, compute_taw(fc, wp, zr))
                )
            return self._dr_hat
        if self.estimator == "openloop":
            if prev is not None:
                self._dr_ol = simulate_water_balance_step(
                    dr_prev_mm=self._dr_ol,
                    eto_mm=self.bias * float(prev["eto_mm"]),
                    kc=float(prev["kc"]),
                    precip_mm=float(prev["rain_mm"]),
                    irrigation_mm=self._last_dose,
                    theta_fc=fc,
                    theta_wp=wp,
                    root_depth_m=zr,
                    p_depletion=float(soil.p_depletion.value),
                    irr_efficiency=eff,
                    runoff_thresh_mm=float(soil.runoff_threshold_mm.value),
                ).depletion_mm
            return self._dr_ol
        # enkf
        if prev is not None:
            self._enkf.forecast_step(
                eto_mm=self.bias * float(prev["eto_mm"]),
                kc=float(prev["kc"]),
                precip_mm=float(prev["rain_mm"]),
                irrigation_mm=self._last_dose,
                irr_efficiency=eff,
            )
        dr_mean, _, _ = self._enkf.analysis_step(sensor_theta_obs if has_obs else None)
        return dr_mean

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
        if day_idx == 0:
            self._reset(config)
        dr_hat = self._estimate(state_depletion_mm, sensor_theta_obs, config)
        self.est_log.append((dr_hat, state_depletion_mm))

        f = self._features(day_idx, current_date, weather_row, dr_hat)
        self._finish_day(weather_row)
        self._prev_row = weather_row[["eto_mm", "rain_mm", "kc"]].copy()

        dose = 0.0
        if not np.isnan(f["eto_lag1"]):
            soil = config.soil
            raw = compute_raw(
                compute_taw(soil.theta_fc.value, soil.theta_wp.value, soil.root_depth_m.value),
                soil.p_depletion.value,
            )
            need = dr_hat + f["kc"] * self.bias * f["eto_lag1"] - self.target_frac * raw
            if need > 0.0:
                eff = float(config.irrigation.efficiency.value)
                dose = float(min(need / eff, float(config.irrigation.max_gross_dose_mm.value)))
        self._last_dose = dose
        return dose

    def estimation_error(self) -> Dict[str, float]:
        """Sezon boyunca Dr̂_{t-1} − Dr_{t-1} hatasının RMSE ve ortalaması [mm]."""
        if not self.est_log:
            return {"est_rmse_mm": np.nan, "est_bias_mm": np.nan}
        err = np.array([h - t for h, t in self.est_log])
        return {"est_rmse_mm": float(np.sqrt(np.mean(err**2))), "est_bias_mm": float(np.mean(err))}


def noisy_state_experiment(
    seasons: Dict[int, pd.DataFrame],
    config: Optional[TwinConfig] = None,
    estimators: tuple = ESTIMATORS,
    biases: tuple = (0.9, 1.0, 1.1),
    margins: tuple = (0.9, 0.8),
    seeds: tuple = tuple(range(10)),
) -> pd.DataFrame:
    """S5'i durum kestiricisi × ETo yanlılığı × güvenlik payı × tohum ızgarasında koşturur.

    Kâhin W* gerçek hava ve b = 1 ile, tam RAW hedefli alt sınırdır. Referans olarak aynı
    tohumlarla S2 (gerçek Dr) ve S4 (EnKF, mevcut uygulama) da koşar. Tohum, motorun sensör
    gürültüsünü ve S5-EnKF topluluğunu belirler.
    """
    from twin.sim.efficiency import water_balance_accounting
    from twin.sim.engine import simulate_strategy_season
    from twin.sim.strategies import S2ETOnly, S4AssimilatedTwin

    cfg = config or TwinConfig()
    rows = []
    for year, weather in seasons.items():
        oracle_df, _ = simulate_strategy_season(OracleJustInTime(), weather, config=cfg)
        w_star = float(oracle_df["irrigation_gross_mm"].sum())
        src = weather.attrs.get("source", "unknown")

        def record(df, **keys):
            acc = water_balance_accounting(df)
            rows.append(
                {
                    "season": year,
                    **keys,
                    "irrigation_gross_mm": acc["irrigation_gross_mm"],
                    "excess_vs_oracle_mm": acc["irrigation_gross_mm"] - w_star,
                    "stress_days": int((df["ks"] < 0.999).sum()),
                    "cumulative_stress": float((1.0 - df["ks"]).clip(lower=0.0).sum()),
                    "deep_percolation_mm": acc["deep_percolation_mm"],
                    "oracle_gross_mm": w_star,
                    "source": src,
                }
            )

        for seed in seeds:
            for name, strat in (("S2", S2ETOnly()), ("S4", S4AssimilatedTwin(use_enkf=True))):
                df, _ = simulate_strategy_season(strat, weather, config=cfg, seed=seed)
                record(
                    df,
                    strategy=name,
                    estimator="-",
                    eto_bias=np.nan,
                    margin=np.nan,
                    seed=seed,
                    est_rmse_mm=np.nan,
                    est_bias_mm=np.nan,
                )
            for est in estimators:
                for b in biases:
                    for f in margins:
                        pol = EstimatedPersistenceJIT(est, f, b, seed=seed)
                        df, _ = simulate_strategy_season(pol, weather, config=cfg, seed=seed)
                        record(
                            df,
                            strategy="S5",
                            estimator=est,
                            eto_bias=b,
                            margin=f,
                            seed=seed,
                            **pol.estimation_error(),
                        )
    return pd.DataFrame(rows)
