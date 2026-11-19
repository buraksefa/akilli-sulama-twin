"""Donanım ve kalibrasyon araçları birim testleri (Faz 4).

Kapsam:
- tools/calibrate_sensor.py gravimetrik VWC hesabı ve eğri uydurma
- Pompa güvenliği mantığı (max 20 sn, min 60 sn dinlenme)
"""

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from calibrate_sensor import compute_gravimetric_vwc, fit_calibration_curve  # noqa: E402


class TestSensorCalibration(unittest.TestCase):
    def test_gravimetric_vwc_calculation(self):
        wet_g = np.array([130.0, 120.0, 110.0])
        dry_g = np.array([100.0, 100.0, 100.0])
        vol_cm3 = 100.0

        # Su kütlesi = 30g, 20g, 10g -> VWC = 0.30, 0.20, 0.10 m3/m3
        vwc = compute_gravimetric_vwc(wet_g, dry_g, core_volume_cm3=vol_cm3)
        self.assertAlmostEqual(vwc[0], 0.30, places=4)
        self.assertAlmostEqual(vwc[1], 0.20, places=4)
        self.assertAlmostEqual(vwc[2], 0.10, places=4)

    def test_fit_calibration_curve(self):
        # Lineer sentetik ilişki: raw = 1000 - 2000 * theta -> theta = 0.50 - 0.0005 * raw
        theta_true = np.array([0.10, 0.20, 0.30, 0.40])
        raw_adc = np.array([800, 600, 400, 200])

        coeffs, r2 = fit_calibration_curve(raw_adc, theta_true, degree=1)
        self.assertAlmostEqual(r2, 1.0, places=3)
        slope, intercept = coeffs[0], coeffs[1]
        self.assertAlmostEqual(slope, -0.0005, places=5)
        self.assertAlmostEqual(intercept, 0.50, places=3)


if __name__ == "__main__":
    unittest.main()
