"""Çekirdek kütüphane birim testleri (Faz 1).

Kapsam:
- data: era5, parks, sentinel2
- model: et0, kc, waterbalance (kütle korunumu dahil), assimilation
- qc: kurallar, isolation forest, arima residual, virtual sensor
- forecast: knn, sarima
"""

import unittest

import numpy as np
import pandas as pd

from twin.config import DEFAULT_CONFIG, VerificationStatus
from twin.data import (
    Sentinel2NDVIProvider,
    aggregate_hourly_to_daily,
    deaccumulate_era5_hourly,
    generate_synthetic_era5,
    generate_synthetic_ndvi_timeseries,
    get_default_zones,
    joules_m2_to_mj_m2,
    joules_m2_to_watts_m2,
    kelvin_to_celsius,
    load_parks,
    meters_to_mm,
    relative_humidity_from_dewpoint,
    wind10m_to_wind2m,
)
from twin.forecast import RollingKNNForecaster, SarimaBaselineForecaster
from twin.model import (
    DirectNudgingAssimilation,
    EnsembleKalmanFilter,
    SensorCalibrationErrorModel,
    atmospheric_pressure,
    compute_ks,
    compute_raw,
    compute_taw,
    fao56_penman_monteith_daily,
    fao56_penman_monteith_hourly,
    get_ndvi_based_kc,
    get_stage_based_kc,
    hargreaves_samani_daily,
    psychrometric_constant,
    simulate_water_balance_step,
)
from twin.qc import (
    ArimaResidualQC,
    IsolationForestQC,
    PhysicalModelVirtualSensor,
    SpatialMLPVirtualSensor,
)


class TestConfig(unittest.TestCase):
    def test_default_config_structure_and_sources(self):
        cfg = DEFAULT_CONFIG
        self.assertEqual(cfg.soil.theta_fc.status, VerificationStatus.ASSUMPTION)
        self.assertIn("FAO-56", cfg.soil.theta_fc.source)
        self.assertEqual(cfg.irrigation.max_pump_s.value, 20)
        self.assertEqual(cfg.irrigation.min_rest_s.value, 60)
        d = cfg.to_dict()
        self.assertIn("soil", d)
        self.assertIn("crop", d)
        self.assertIn("irrigation", d)


class TestDataLoaders(unittest.TestCase):
    def test_era5_conversions(self):
        self.assertAlmostEqual(kelvin_to_celsius(273.15), 0.0, places=4)
        self.assertAlmostEqual(kelvin_to_celsius(300.0), 26.85, places=2)
        self.assertAlmostEqual(meters_to_mm(0.005), 5.0, places=4)
        self.assertAlmostEqual(joules_m2_to_watts_m2(3600.0), 1.0, places=4)
        self.assertAlmostEqual(joules_m2_to_mj_m2(1e6), 1.0, places=4)
        # Logarithmic wind profile test
        u2 = wind10m_to_wind2m(10.0)
        self.assertAlmostEqual(u2, 7.48, delta=0.1)

    def test_era5_deaccumulation(self):
        # 3 günlük saatlik indeks
        times = pd.date_range("2024-06-01 00:00", "2024-06-02 03:00", freq="h", tz="UTC")
        # 00 UTC'de sıfır veya sıfırlanıp 01'den itibaren biriken değerler
        accum = [0.0, 2.0, 5.0, 9.0] + [0.0] * 20 + [0.0, 3.0, 7.0, 8.0]
        s = pd.Series(accum[: len(times)], index=times)
        deaccum = deaccumulate_era5_hourly(s, times)
        self.assertEqual(deaccum.iloc[1], 2.0)  # 01:00 UTC
        self.assertEqual(deaccum.iloc[2], 3.0)  # 02:00 UTC (5 - 2)
        self.assertEqual(deaccum.iloc[3], 4.0)  # 03:00 UTC (9 - 5)

    def test_relative_humidity_from_dewpoint(self):
        rh = relative_humidity_from_dewpoint(temp_c=25.0, dewpoint_c=25.0)
        self.assertAlmostEqual(rh, 100.0, places=1)
        rh_low = relative_humidity_from_dewpoint(temp_c=25.0, dewpoint_c=10.0)
        self.assertTrue(30.0 < rh_low < 50.0)

    def test_synthetic_era5_generation_and_daily_aggregation(self):
        df_hourly = generate_synthetic_era5("2024-05-01", "2024-05-10 23:00", seed=42)
        self.assertEqual(len(df_hourly), 10 * 24)
        self.assertIn("temp_c", df_hourly.columns)
        self.assertIn("rain_mm", df_hourly.columns)

        df_daily = aggregate_hourly_to_daily(df_hourly)
        self.assertTrue(len(df_daily) >= 10)
        self.assertIn("temp_max", df_daily.columns)
        self.assertTrue((df_daily["temp_max"] >= df_daily["temp_min"]).all())

    def test_parks_loader(self):
        parks = load_parks()
        self.assertIn("macka", parks)
        self.assertIn("yildiz", parks)
        self.assertGreater(parks["yildiz"].area_m2, 100000.0)
        zones = get_default_zones("yildiz")
        self.assertTrue(len(zones) >= 1)
        self.assertEqual(zones[0].park_id, "yildiz")

    def test_sentinel2_ndvi(self):
        df_ndvi = generate_synthetic_ndvi_timeseries("2024-04-01", "2024-05-01", seed=42)
        self.assertTrue("ndvi" in df_ndvi.columns)
        provider = Sentinel2NDVIProvider()
        df_daily = provider.get_park_ndvi("yildiz", "2024-04-01", "2024-04-30")
        self.assertEqual(len(df_daily), 30)
        self.assertTrue((df_daily["ndvi"] >= 0.0).all())


class TestET0Model(unittest.TestCase):
    def test_atmospheric_pressure_and_psychrometric(self):
        # Deniz seviyesi (z=0) -> P ≈ 101.3 kPa, gamma ≈ 0.0673 kPa/°C
        p0 = atmospheric_pressure(0.0)
        self.assertAlmostEqual(p0, 101.3, places=1)
        g0 = psychrometric_constant(p0)
        self.assertAlmostEqual(g0, 0.0673, places=3)

    def test_fao56_example_18_brussels_benchmark(self):
        """FAO-56 Bölüm 4 Örnek 18 (Brüksel, 6 Temmuz) referans çözümü ile sayısal doğrulama.

        FAO-56 Box 18 girdi parametreleri:
        - Enlem: 50.80° N, Rakım: 100 m, Yılın günü: 187 (6 Temmuz)
        - Tmax = 21.5 °C, Tmin = 12.3 °C (Tmean = 16.9 °C)
        - u2 = 2.078 m/s (2 m rüzgâr hızı)
        - Rs = 22.07 MJ/m²/gün
        - RHmax = 84%, RHmin = 63% (RHmean = 73.5%)

        Referans FAO-56 ETo çözümü: 3.88 mm/gün (Tolerans: ±0.02 mm/gün).
        """
        eto = fao56_penman_monteith_daily(
            temp_mean_c=16.9,
            temp_max_c=21.5,
            temp_min_c=12.3,
            wind_speed_2m_ms=2.078,
            rad_mj_m2_day=22.07,
            rh_max_pct=84.0,
            rh_min_pct=63.0,
            day_of_year=187,
            latitude_deg=50.80,
            elevation_m=100.0,
        )
        self.assertAlmostEqual(eto, 3.88, delta=0.02, msg=f"FAO-56 Örnek 18 çözümü: {eto:.4f} mm/gün")

    def test_fao56_penman_monteith_daily_reasonable_range(self):
        # Makul aralık kontrolü: Yaz günü Marmara iklimi
        # Tmean=25, Tmax=30, Tmin=20, u2=2.0 m/s, Rs=22 MJ/m2/day, RH=50%
        eto = fao56_penman_monteith_daily(
            temp_mean_c=25.0,
            temp_max_c=30.0,
            temp_min_c=20.0,
            wind_speed_2m_ms=2.0,
            rad_mj_m2_day=22.0,
            rh_mean_pct=50.0,
            day_of_year=180,
            latitude_deg=41.04,
            elevation_m=30.0,
        )
        # Tipik Akdeniz/Marmara yaz ETo değeri 4.0 - 6.5 mm/gün aralığındadır
        self.assertTrue(4.0 <= eto <= 6.5, f"Hesaplanan ETo: {eto}")

    def test_hargreaves_samani_vs_pm(self):
        eto_hs = hargreaves_samani_daily(
            temp_mean_c=25.0,
            temp_max_c=30.0,
            temp_min_c=20.0,
            day_of_year=180,
            latitude_deg=41.04,
        )
        self.assertTrue(3.5 <= eto_hs <= 7.0, f"Hesaplanan HS ETo: {eto_hs}")

    def test_fao56_hourly_eto(self):
        eto_hr = fao56_penman_monteith_hourly(
            temp_c=28.0,
            rh_pct=45.0,
            wind_speed_2m_ms=2.5,
            rad_mj_m2_h=2.5,  # öğle vakti ~700 W/m2
            day_of_year=180,
            hour_of_day=13,
        )
        self.assertTrue(0.2 <= eto_hr <= 1.0, f"Hesaplanan saatlik ETo: {eto_hr}")


class TestCropAndWaterBalance(unittest.TestCase):
    def test_kc_calculation(self):
        kc_mid = get_stage_based_kc(month=7, veg_type="lawn")
        self.assertAlmostEqual(kc_mid, 0.95, places=2)
        kc_ndvi = get_ndvi_based_kc(ndvi=0.80, exponent=2.0)
        self.assertAlmostEqual(kc_ndvi, 0.64, places=2)

    def test_taw_raw_ks_relations(self):
        theta_fc = 0.28
        theta_wp = 0.14
        root_depth = 0.30
        taw = compute_taw(theta_fc, theta_wp, root_depth)
        self.assertAlmostEqual(taw, 42.0, places=2)  # 1000 * 0.14 * 0.30 = 42 mm

        raw = compute_raw(taw, p_depletion=0.50)
        self.assertAlmostEqual(raw, 21.0, places=2)

        # Dr <= RAW iken Ks = 1.0
        self.assertEqual(compute_ks(dr_mm=10.0, taw_mm=taw, raw_mm=raw, p_depletion=0.50), 1.0)
        # Dr > RAW iken Ks < 1.0
        ks_stressed = compute_ks(dr_mm=31.5, taw_mm=taw, raw_mm=raw, p_depletion=0.50)
        self.assertAlmostEqual(ks_stressed, 0.50, places=2)

    def test_water_balance_mass_closure(self):
        """Su dengesi kütle korunumunun (Inputs - Outputs == ΔStorage) kapandığını doğrular."""
        dr_initial = 10.0
        eto = 5.0
        kc = 1.0
        precip = 15.0
        irrigation = 0.0

        state = simulate_water_balance_step(
            dr_prev_mm=dr_initial,
            eto_mm=eto,
            kc=kc,
            precip_mm=precip,
            irrigation_mm=irrigation,
            theta_fc=0.28,
            theta_wp=0.14,
            root_depth_m=0.30,
            p_depletion=0.50,
            irr_efficiency=1.0,
        )

        dr_final = state.depletion_mm
        # Depolama değişimi ΔS = -(Dr_final - Dr_initial)
        delta_storage = -(dr_final - dr_initial)

        # Girdiler: Yağış + Sulama (Net)
        inputs = (precip - state.ro_mm) + irrigation
        # Çıktılar: ETa + DP
        outputs = state.eta_mm + state.dp_mm

        # Mass conservation: Inputs - Outputs == ΔStorage
        self.assertAlmostEqual(inputs - outputs, delta_storage, places=5)


class TestAssimilation(unittest.TestCase):
    def test_sensor_error_model(self):
        model = SensorCalibrationErrorModel(slope=1.1, bias=0.02, noise_std=0.01)
        obs = model.observe(0.25, rng=np.random.default_rng(42))
        corr = model.invert(obs)
        self.assertAlmostEqual(corr, 0.25, delta=0.03)

    def test_nudging_and_enkf_updates(self):
        nudging = DirectNudgingAssimilation(nudge_factor=0.40)
        dr_nudge = nudging.update(dr_model=20.0, theta_obs=0.25, theta_fc=0.28, root_depth_m=0.30)
        self.assertTrue(0.0 <= dr_nudge <= 42.0)

        enkf = EnsembleKalmanFilter(num_members=30, seed=42)
        enkf.forecast_step(eto_mm=4.0, kc=0.85, precip_mm=0.0, irrigation_mm=0.0)
        dr_mean, dr_std, theta_mean = enkf.analysis_step(theta_obs=0.26)
        self.assertTrue(0.0 <= theta_mean <= 0.35)
        self.assertGreater(dr_std, 0.0)


class TestQualityControlAndVirtualSensor(unittest.TestCase):
    def test_simpact_missing_rate_rule(self):
        from twin.qc.rules import check_missing_rate

        # %60 eksik veri içeren seri -> is_fault True olmalı
        s_bad = pd.Series([0.25, np.nan, np.nan, 0.26, np.nan, np.nan, 0.24, np.nan, np.nan, 0.25])
        is_bad, ratio_bad = check_missing_rate(s_bad, threshold=0.50)
        self.assertTrue(is_bad)
        self.assertAlmostEqual(ratio_bad, 0.60, places=2)

        # %20 eksik veri içeren seri -> is_fault False olmalı
        s_good = pd.Series([0.25, 0.26, np.nan, 0.24, 0.25])
        is_good, ratio_good = check_missing_rate(s_good, threshold=0.50)
        self.assertFalse(is_good)
        self.assertAlmostEqual(ratio_good, 0.20, places=2)

    def test_simpact_3day_gap_rule(self):
        from twin.qc.rules import find_3day_gaps

        t0 = pd.Timestamp("2024-05-01 00:00:00", tz="UTC")
        t1 = pd.Timestamp("2024-05-01 01:00:00", tz="UTC")
        t2 = pd.Timestamp("2024-05-05 02:00:00", tz="UTC")  # ~97 saatlik boşluk (> 72h)
        df_gap = pd.DataFrame({"time": [t0, t1, t2], "val": [0.25, 0.25, 0.26]})
        gaps = find_3day_gaps(df_gap, max_gap_hours=72.0)
        self.assertEqual(len(gaps), 1)
        self.assertGreater(gaps["hours"].iloc[0], 72.0)

    def test_simpact_120h_frozen_rule(self):
        from twin.qc.rules import check_120h_frozen

        times = pd.date_range("2024-05-01", periods=150, freq="h")
        # Sabit 0.25 değeri (değişim %0)
        s_frozen = pd.Series([0.25] * 150)
        flags = check_120h_frozen(s_frozen, timestamps=times, max_variation_pct=1.0)
        # 120 saatten sonraki değerler bayraklanmalı
        self.assertTrue(flags.iloc[130])

    def test_simpact_rolling_median_24h_spike_rule(self):
        from twin.qc.rules import spikes_rolling_median_24h

        times = pd.date_range("2024-05-01", periods=100, freq="h")
        vals = [0.25] * 100
        vals[50] = 0.85  # Ani sıçrama
        s_spike = pd.Series(vals)
        spike_flags = spikes_rolling_median_24h(s_spike, timestamps=times, k=4.0)
        self.assertTrue(spike_flags.iloc[50])

    def test_simpact_physical_range_rule(self):
        from twin.qc.rules import check_physical_range

        s_temp = pd.Series([-5.0, 22.0, 55.0, np.nan])
        flags_temp = check_physical_range(s_temp, min_val=0.0, max_val=50.0)
        self.assertTrue(flags_temp.iloc[0])  # -5.0 sınır dışı
        self.assertFalse(flags_temp.iloc[1])  # 22.0 normal
        self.assertTrue(flags_temp.iloc[2])  # 55.0 sınır dışı
        self.assertTrue(flags_temp.iloc[3])  # NaN aralık dışı sayılır

    def test_isolation_forest_and_arima_qc(self):
        rng = np.random.default_rng(42)
        # Normal seri + anomali bloğu
        clean = 0.25 + 0.02 * np.sin(np.linspace(0, 10, 100)) + rng.normal(0, 0.002, 100)
        clean[40:55] = 0.90  # Anomali bloğu
        s = pd.Series(clean)

        if_qc = IsolationForestQC(n_estimators=100, contamination=0.10, random_state=42)
        flags, is_fault, ratio = if_qc.detect_anomalies(s)
        self.assertTrue(flags.iloc[45])  # Anomali bloğu yakalanmalı

        arima_qc = ArimaResidualQC(forecast_horizon=24)
        train_s = pd.Series(clean[:70])
        test_s = pd.Series(clean[70:])
        flags_ar, is_fault_ar, ratio_ar = arima_qc.check_residuals(train_s, test_s)
        self.assertEqual(len(flags_ar), len(test_s))

    def test_virtual_sensor_fallback(self):
        weather = pd.DataFrame(
            {
                "eto_mm": [4.0, 5.0, 4.5, 4.0],
                "rain_mm": [0.0, 0.0, 10.0, 0.0],
            },
            index=pd.date_range("2024-05-01", periods=4, freq="D"),
        )
        phys_vs = PhysicalModelVirtualSensor()
        vwc = phys_vs.estimate_vwc(weather, kc_series=0.85)
        self.assertEqual(len(vwc), 4)
        self.assertTrue((vwc >= 0.14).all() and (vwc <= 0.28).all())

    def test_spatial_mlp_virtual_sensor(self):
        t = np.linspace(0, 10, 50)
        s_target = pd.Series(0.25 + 0.05 * np.sin(t))
        s_peer = pd.Series(0.24 + 0.04 * np.sin(t) + 0.01)
        peer_df = pd.DataFrame({"peer1": s_peer, "peer2": np.random.default_rng(42).normal(0.2, 0.01, 50)})

        mlp_vs = SpatialMLPVirtualSensor(max_iter=400)
        best_n = mlp_vs.select_best_neighbor(s_target, peer_df)
        self.assertEqual(best_n, "peer1")
        mlp_vs.fit(s_target, s_peer)
        preds = mlp_vs.predict(s_peer)
        self.assertEqual(len(preds), 50)


class TestForecasting(unittest.TestCase):
    def test_sarima_forecaster(self):
        t = np.linspace(0, 10, 60)
        series = pd.Series(0.25 + 0.05 * np.sin(t))
        sarima = SarimaBaselineForecaster(forecast_horizon=12)
        preds = sarima.fit_predict(series)
        self.assertEqual(len(preds), 12)

    def test_knn_forecaster(self):
        t = np.linspace(0, 20, 200)
        series = pd.Series(0.25 + 0.05 * np.sin(t))
        knn = RollingKNNForecaster(history_window=24, forecast_horizon=12, n_neighbors=3)
        knn.fit(series)
        preds = knn.predict(series.iloc[-24:])
        self.assertEqual(len(preds), 12)
        self.assertTrue((preds >= 0.15).all() and (preds <= 0.35).all())


if __name__ == "__main__":
    unittest.main()
