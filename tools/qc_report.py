#!/usr/bin/env python3
"""Sensör verisi için temel kalite kontrol raporu.

`src/twin/qc` modülünü kullanarak çalışır.
Kontroller:
  - boşluklar: beklenen aralığın 1,5 katından uzun kesintiler
  - yeniden başlatmalar: sıra numarası (seq) geriye giderse
  - donmuş değer: aynı değerin art arda N kez tekrarı (kopuk/takılı sensör şüphesi)
  - sıçrama: ardışık farkın robust (MAD) eşiğini aşması
  - fiziksel sınır dışı: DHT11 belirtimi 0-50 C, %20-90 nem; toprak ham değeri 0-1023
  - firmware hata bayrakları (err): 1 DHT, 2 toprak, 4 WiFi, 8 ThingSpeak, 16 MQTT

Kullanım:
    python tools/qc_report.py data/raw/serial_log.csv --interval 60 [--flags-out data/processed/flags.csv]
"""

import argparse
import sys
from pathlib import Path

# Proje kökünü sys.path'e ekle
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd  # noqa: E402

from twin.qc import (  # noqa: E402
    ERR_BITS,
    find_gaps,
    find_restarts,
    flatline_runs,
    spikes,
)
from twin.qc import (
    load_sensor_csv as load,
)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--interval", type=float, default=60, help="beklenen ölçüm aralığı (sn)")
    ap.add_argument("--flat-min", type=int, default=30, help="donmuş değer için art arda tekrar sayısı")
    ap.add_argument("--flags-out", help="işaretli satırları CSV olarak yaz")
    args = ap.parse_args()

    df = load(args.csv)
    n = len(df)
    print(f"Kayıt sayısı: {n}")
    if n == 0:
        sys.exit(0)
    print(f"Aralık: {df['time'].iloc[0]} -> {df['time'].iloc[-1]}")

    span = (df["time"].iloc[-1] - df["time"].iloc[0]).total_seconds()
    expected = int(span / args.interval) + 1
    print(f"Beklenen kayıt: ~{expected}, eksik oran: {max(0.0, 1 - n / expected):.1%}")

    gaps = find_gaps(df, args.interval)
    print(f"\nBoşluklar (> {1.5 * args.interval:.0f} sn): {len(gaps)}")
    if len(gaps):
        print(gaps.head(10).to_string(index=False))

    restarts = find_restarts(df)
    print(f"\nYeniden başlatma (seq geriye gitti): {len(restarts)}")

    flags = pd.DataFrame(index=df.index)
    for col in ["soil_raw", "soil_pct", "temp_c", "hum_pct"]:
        if col not in df.columns:
            continue
        runs = flatline_runs(df[col], args.flat_min)
        flags[f"{col}_flat"] = False
        for a, b in runs:
            flags.loc[a:b, f"{col}_flat"] = True
        sp = spikes(df[col])
        flags[f"{col}_spike"] = df.index.isin(sp)
        print(f"{col}: donmuş aralık={len(runs)}, sıçrama={len(sp)}, boş={int(df[col].isna().sum())}")

    out_of_range = pd.Series(False, index=df.index)
    if "temp_c" in df.columns:
        t = pd.to_numeric(df["temp_c"], errors="coerce")
        out_of_range |= (t < 0) | (t > 50)
    if "hum_pct" in df.columns:
        h = pd.to_numeric(df["hum_pct"], errors="coerce")
        out_of_range |= (h < 20) | (h > 90)
    if "soil_raw" in df.columns:
        r = pd.to_numeric(df["soil_raw"], errors="coerce")
        out_of_range |= (r < 0) | (r > 1023)
    flags["out_of_range"] = out_of_range
    print(f"\nFiziksel sınır dışı: {int(out_of_range.sum())}")

    if "err" in df.columns:
        err = pd.to_numeric(df["err"], errors="coerce").fillna(0).astype(int)
        print("\nFirmware hata bayrakları:")
        for bit, name in ERR_BITS.items():
            c = int(((err & bit) > 0).sum())
            flags[f"err_{name}"] = (err & bit) > 0
            print(f"  {name}: {c}")

    if args.flags_out:
        out = pd.concat([df[["time"]], flags], axis=1)
        out.to_csv(args.flags_out, index=False)
        print(f"\nBayraklar yazıldı: {args.flags_out}")


if __name__ == "__main__":
    main()
