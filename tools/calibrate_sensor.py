#!/usr/bin/env python3
"""Toprak nemi sensörü gravimetrik kalibrasyon aracı.

Kurutarak tartma (gravimetric method) ile elde edilen laboratuvar ölçümlerinden:
  theta_vwc = (W_wet - W_dry) / (rho_water * V_core)
formülüyle gerçek hacimsel su içeriğini hesaplar ve ham sensör (raw ADC)
değerlerine doğrusal / polinom kalibrasyon eğrisi uydurur.

Çıktı olarak C başlık dosyası (#define CALIB_SLOPE ...) parametrelerini üretir.

Kullanım:
    python tools/calibrate_sensor.py data/raw/calibration_samples.csv [--degree 1] [--out-config]
"""

import argparse
import sys
from typing import Tuple

import numpy as np
import pandas as pd


def compute_gravimetric_vwc(
    wet_weight_g: np.ndarray,
    dry_weight_g: np.ndarray,
    core_volume_cm3: float = 100.0,
    water_density_g_cm3: float = 1.0,
) -> np.ndarray:
    """Yaş ve kuru toprak ağırlıklarından hacimsel su içeriğini (theta [m3/m3]) hesaplar."""
    water_mass_g = wet_weight_g - dry_weight_g
    water_vol_cm3 = water_mass_g / water_density_g_cm3
    theta = water_vol_cm3 / core_volume_cm3
    return np.clip(theta, 0.0, 0.60)


def fit_calibration_curve(
    raw_adc: np.ndarray,
    theta_vwc: np.ndarray,
    degree: int = 1,
) -> Tuple[np.ndarray, float]:
    """ADC ham değerleri ile VWC arasına polinom uydurur ve R2 skoru döner."""
    poly_coeffs = np.polyfit(raw_adc, theta_vwc, deg=degree)
    y_pred = np.polyval(poly_coeffs, raw_adc)

    # R2 Skoru
    ss_res = np.sum((theta_vwc - y_pred) ** 2)
    ss_tot = np.sum((theta_vwc - np.mean(theta_vwc)) ** 2)
    r2 = 1.0 - (ss_res / (ss_tot + 1e-8))
    return poly_coeffs, float(r2)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("csv", help="Kalibrasyon CSV dosyası (raw, wet_g, dry_g, vol_cm3)")
    parser.add_argument("--degree", type=int, default=1, help="Polinom derecesi (1=Doğrusal, 2=Karesel)")
    args = parser.parse_args()

    df = pd.read_csv(args.csv)
    req_cols = ["raw", "wet_g", "dry_g"]
    for col in req_cols:
        if col not in df.columns:
            print(
                f"Hata: CSV dosyasında '{col}' sütunu bulunamadı. Gerekli sütunlar: {req_cols}",
                file=sys.stderr,
            )
            sys.exit(1)

    vol = df["vol_cm3"].iloc[0] if "vol_cm3" in df.columns else 100.0
    theta = compute_gravimetric_vwc(df["wet_g"].values, df["dry_g"].values, core_volume_cm3=vol)
    raw = df["raw"].values

    coeffs, r2 = fit_calibration_curve(raw, theta, degree=args.degree)

    print(f"\n--- Gravimetrik Kalibrasyon Sonucu (N={len(df)}) ---")
    print(f"Uydurma Belirleme Katsayısı (R²): {r2:.4f}")

    if args.degree == 1:
        slope, intercept = coeffs[0], coeffs[1]
        print(f"Doğrusal Model: theta = ({slope:.6f}) * raw + ({intercept:.4f})")
        print("\nC Kodu için (config.h):")
        print(f"#define CALIB_SLOPE {slope:.6f}f")
        print(f"#define CALIB_INTERCEPT {intercept:.4f}f")
    else:
        print(f"Polinom Katsayıları (azalan dereceli): {coeffs}")


if __name__ == "__main__":
    main()
