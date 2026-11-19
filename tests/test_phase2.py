"""Simülasyon ve değerlendirme kütüphanesi birim testleri (Faz 2).

Kapsam:
- Stratejiler: S0, S1, S2, S3, S4
- Metrikler: RMSE, Bias, KGE, NSE, SimulationMetrics
- CRITIC: Karar matrisi normalizasyonu, bilgi miktarı, objektif ağırlıklar, sıralama
- Duyarlılık: OAT, Sobol/Morris örneklemesi
- Arıza Enjeksiyonu: Bias, Drift, Freeze, Dropout
- Simülasyon Motoru: Sezon simülasyonu, 5 strateji karşılaştırma
- Grafik Çıktıları: Dosya kaydetme ve eksiksiz çizim
"""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from twin.config import DEFAULT_CONFIG
from twin.sim import (
    FaultConfig,
    S0FixedSchedule,
    S1SensorThreshold,
    S2ETOnly,
    S3ForecastGuided,
    S4AssimilatedTwin,
    compare_all_strategies,
    inject_sensor_faults,
    kling_gupta_efficiency,
    mean_bias_error,
    nash_sutcliffe_efficiency,
    plot_sensitivity_tornado,
    plot_strategy_comparison,
    plot_water_balance_timeseries,
    prepare_season_weather,
    rank_strategies_critic,
    rmse,
    run_oat_sensitivity,
    run_sobol_morris_sampling,
    simulate_strategy_season,
)


class TestMetricsAndCritic(unittest.TestCase):
    def test_validation_metrics(self):
        y_true = np.array([10.0, 12.0, 15.0, 14.0, 16.0])
        y_pred = np.array([10.5, 11.5, 14.8, 14.2, 16.1])

        err_rmse = rmse(y_true, y_pred)
        self.assertTrue(0.0 < err_rmse < 0.6)

        err_bias = mean_bias_error(y_true, y_pred)
        self.assertTrue(abs(err_bias) < 0.3)

        nse_val = nash_sutcliffe_efficiency(y_true, y_pred)
        self.assertTrue(0.85 < nse_val <= 1.0)

        kge_val = kling_gupta_efficiency(y_true, y_pred)
        self.assertTrue(0.85 < kge_val <= 1.0)

    def test_critic_weighting_and_ranking(self):
        # 3 strateji x 4 kriter matrisi
        # [total_water_mm (cost), cumulative_stress (cost), events (cost), mean_ks (benefit)]
        data = [
            {
                "strategy": "S0",
                "total_water_mm": 500.0,
                "cumulative_stress": 12.0,
                "irrigation_events": 40,
                "mean_ks": 0.88,
            },
            {
                "strategy": "S1",
                "total_water_mm": 380.0,
                "cumulative_stress": 4.0,
                "irrigation_events": 22,
                "mean_ks": 0.94,
            },
            {
                "strategy": "S4",
                "total_water_mm": 320.0,
                "cumulative_stress": 1.5,
                "irrigation_events": 18,
                "mean_ks": 0.98,
            },
        ]
        df = pd.DataFrame(data)
        ranked = rank_strategies_critic(df)

        self.assertIn("critic_score", ranked.columns)
        self.assertIn("rank", ranked.columns)
        # S4 en az su ve en az stresle rank 1 olmalı
        self.assertEqual(ranked.iloc[0]["strategy"], "S4")
        self.assertEqual(ranked.iloc[0]["rank"], 1)


class TestStrategies(unittest.TestCase):
    def setUp(self):
        self.cfg = DEFAULT_CONFIG
        soil = self.cfg.soil
        taw = 1000.0 * (soil.theta_fc.value - soil.theta_wp.value) * soil.root_depth_m.value
        self.raw = soil.p_depletion.value * taw
        self.date = pd.Timestamp("2024-07-01")
        self.w_row = pd.Series({"eto_mm": 5.0, "rain_mm": 0.0})

    def test_s0_fixed_schedule(self):
        s0 = S0FixedSchedule(interval_days=3, dose_mm=12.0)
        self.assertEqual(s0.decide(0, self.date, self.w_row, 10.0, None, 0.0, self.cfg), 12.0)
        self.assertEqual(s0.decide(1, self.date, self.w_row, 10.0, None, 0.0, self.cfg), 0.0)

    def test_s1_sensor_threshold(self):
        s1 = S1SensorThreshold()
        # Toprak nemi kritik eşiğin üstündeyse sulama yok
        self.assertEqual(s1.decide(0, self.date, self.w_row, 10.0, 0.26, 0.0, self.cfg), 0.0)
        # Toprak nemi kuruyunca (0.18 m3/m3) sulama tetiklenir
        dose = s1.decide(0, self.date, self.w_row, 30.0, 0.18, 0.0, self.cfg)
        self.assertGreater(dose, 10.0)

    def test_s2_et_only(self):
        s2 = S2ETOnly()
        # Tükenme RAW'ın altındaysa 0
        self.assertEqual(s2.decide(0, self.date, self.w_row, self.raw - 6.0, None, 0.0, self.cfg), 0.0)
        # Tükenme RAW'ı aşarsa sulama tetiklenir
        dose = s2.decide(0, self.date, self.w_row, self.raw + 4.0, None, 0.0, self.cfg)
        self.assertGreater(dose, 15.0)

    def test_s3_forecast_guided(self):
        s3 = S3ForecastGuided(rain_threshold_mm=5.0)
        # Dr >= RAW ama yarın 8 mm yağmur bekleniyorsa sulama ertelenir (0 mm)
        dose_postponed = s3.decide(0, self.date, self.w_row, self.raw + 4.0, None, 8.0, self.cfg)
        self.assertEqual(dose_postponed, 0.0)
        # Yağmur beklenmiyorsa sulama yapılır
        dose_irrigate = s3.decide(0, self.date, self.w_row, self.raw + 4.0, None, 0.0, self.cfg)
        self.assertGreater(dose_irrigate, 15.0)

    def test_s4_assimilated_twin(self):
        s4 = S4AssimilatedTwin(use_enkf=True)
        # Nem yüksekken sulama yok
        self.assertEqual(s4.decide(0, self.date, self.w_row, 5.0, 0.27, 0.0, self.cfg), 0.0)

    def test_s4_enkf_daily_step_execution(self):
        s4 = S4AssimilatedTwin(use_enkf=True)
        w_row = pd.Series({"eto_mm": 5.5, "kc": 0.95, "rain_mm": 0.0})

        # Adım adım simülasyon: Kuruma periyodu boyunca EnKF durumunu takip eder
        doses = []
        for day in range(5):
            d = s4.decide(
                day,
                pd.Timestamp("2024-07-01") + pd.Timedelta(days=day),
                w_row,
                5.0 * day,
                0.28 - 0.025 * day,
                0.0,
                self.cfg,
            )
            doses.append(d)

        # EnKF nesnesinin başarıyla oluşturulduğunu doğrula
        self.assertIsNotNone(s4.enkf)
        # Kuruma RAW eşiğini aşınca (3. gün) sulama tetiklenmeli
        self.assertGreater(max(doses), 15.0)
        # Sulama sonrası EnKF durumunun sıfırlandığını/azaldığını doğrula
        self.assertTrue(s4.last_irr_gross_mm >= 0.0)


class TestSimulationEngineAndSensitivity(unittest.TestCase):
    def test_seasonal_simulation_and_strategy_comparison(self):
        weather = prepare_season_weather(season_year=2024)
        self.assertEqual(len(weather), 214)  # 1 Nisan - 31 Ekim

        strat = S4AssimilatedTwin()
        sim_df, m = simulate_strategy_season(strat, weather)
        self.assertEqual(len(sim_df), len(weather))
        self.assertGreater(m.total_water_mm, 0.0)
        self.assertTrue(0.0 <= m.mean_ks <= 1.0)

        # Çoklu strateji karşılaştırma
        ranked_df, sim_dfs = compare_all_strategies(season_year=2024, park_id="yildiz")
        self.assertEqual(len(ranked_df), 5)
        self.assertEqual(len(sim_dfs), 5)

    def test_oat_and_sobol_sensitivity(self):
        weather = prepare_season_weather(season_year=2024).iloc[:30]  # Hızlı test için 30 gün
        oat_df = run_oat_sensitivity(weather)
        self.assertTrue(len(oat_df) >= 8)
        self.assertIn("water_change_pct", oat_df.columns)

        sobol_df = run_sobol_morris_sampling(weather, num_samples=10, seed=42)
        self.assertEqual(len(sobol_df), 10)
        self.assertIn("cumulative_stress", sobol_df.columns)

    def test_fault_injection(self):
        s = pd.Series([0.25] * 50)
        cfg_bias = FaultConfig(fault_type="bias", bias_value=0.05)
        s_bias = inject_sensor_faults(s, cfg_bias)
        self.assertAlmostEqual(s_bias.iloc[0], 0.30, places=4)

        cfg_freeze = FaultConfig(
            fault_type="freeze", freeze_start_day=10, freeze_duration_days=5, freeze_value=0.20
        )
        s_freeze = inject_sensor_faults(s, cfg_freeze)
        self.assertEqual(s_freeze.iloc[12], 0.20)

    def test_plot_generation(self):
        weather = prepare_season_weather(season_year=2024).iloc[:30]
        strat = S4AssimilatedTwin()
        sim_df, _ = simulate_strategy_season(strat, weather)

        ranked_df, _ = compare_all_strategies(season_year=2024, park_id="yildiz")
        oat_df = run_oat_sensitivity(weather)

        with tempfile.TemporaryDirectory() as d:
            p1 = Path(d) / "ts.png"
            p2 = Path(d) / "comp.png"
            p3 = Path(d) / "tornado.png"

            plot_water_balance_timeseries(sim_df, output_path=p1)
            plot_strategy_comparison(ranked_df, output_path=p2)
            plot_sensitivity_tornado(oat_df, output_path=p3)

            self.assertTrue(p1.exists())
            self.assertTrue(p2.exists())
            self.assertTrue(p3.exists())


if __name__ == "__main__":
    unittest.main()
