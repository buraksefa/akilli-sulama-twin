#!/usr/bin/env python3
"""ERA5-Land saatlik verisini ay ay indirir (NetCDF).

Önkoşul: Copernicus CDS hesabı ve ~/.cdsapirc dosyası (cds.climate.copernicus.eu). Bu script CDS
kimlik bilgisi olmadan çalıştırılamaz; bu yüzden gerçek bir indirmeyle test EDİLMEDİ. Değişken
adları ve istek biçimi CDS'in ERA5-Land sayfasındaki "Show API request" çıktısıyla karşılaştırılmalı.

ERA5-Land ızgarası 0,1 derece (~9 km). Varsayılan kutu Beşiktaş çevresini 1-4 ızgara hücresiyle
karşılar; bu yüzden değerler park ölçeğindeki mikro iklimi değil bölge ortalamasını gösterir.

Kullanım:
    python tools/era5_download.py --start 2025-01 --end 2025-12 --out data/raw/era5land
"""

import argparse
import os
import sys

# Kuzey, Batı, Güney, Doğu (CDS "area" sırası)
DEFAULT_AREA = [41.10, 28.90, 40.95, 29.10]

VARIABLES = [
    "2m_temperature",
    "2m_dewpoint_temperature",
    "total_precipitation",
    "volumetric_soil_water_layer_1",
    "surface_solar_radiation_downwards",
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
    "potential_evaporation",
]


def month_range(start, end):
    """'2025-01' .. '2025-03' -> [(2025,1),(2025,2),(2025,3)]"""
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))
    out = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        out.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def build_request(year, month, area):
    return {
        "variable": VARIABLES,
        "year": f"{year:04d}",
        "month": f"{month:02d}",
        "day": [f"{d:02d}" for d in range(1, 32)],
        "time": [f"{h:02d}:00" for h in range(24)],
        "area": area,
        "data_format": "netcdf",
        "download_format": "unarchived",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True, help="YYYY-MM")
    ap.add_argument("--end", required=True, help="YYYY-MM")
    ap.add_argument("--out", default="data/raw/era5land", help="çıktı klasörü")
    ap.add_argument("--area", nargs=4, type=float, metavar=("N", "W", "S", "E"), default=DEFAULT_AREA)
    args = ap.parse_args()

    import cdsapi

    os.makedirs(args.out, exist_ok=True)
    client = cdsapi.Client()
    for year, month in month_range(args.start, args.end):
        target = os.path.join(args.out, f"era5land_{year:04d}_{month:02d}.nc")
        if os.path.exists(target):
            print(f"Var, atlanıyor: {target}")
            continue
        print(f"İndiriliyor: {year}-{month:02d}", file=sys.stderr)
        client.retrieve("reanalysis-era5-land", build_request(year, month, args.area), target)


if __name__ == "__main__":
    main()
