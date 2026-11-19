#!/usr/bin/env python3
"""NodeMCU'nun seri porttan bastığı JSON satırlarını CSV'ye kaydeder.

Masa başı testlerde (düğüm USB ile bilgisayara/sunucuya bağlıyken) yerel yedek olarak kullanılır.
`#` ile başlayan satırlar (durum mesajları) ve bozuk satırlar atlanır. Port kopsa bile yeniden dener.

Kullanım:
    python tools/serial_logger.py --port /dev/ttyUSB0 --out data/raw/serial_log.csv
    (Windows: --port COM3)
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone

COLUMNS = [
    "pc_time_utc",
    "node",
    "seq",
    "up",
    "ts",
    "soil_raw",
    "soil_pct",
    "temp_c",
    "hum_pct",
    "pump_s",
    "rssi",
    "err",
]


def parse_line(line):
    """Bir seri satırı sözlüğe çevirir. Veri satırı değilse ya da bozuksa None döner."""
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or "seq" not in obj:
        return None
    return obj


def to_row(obj, now=None):
    now = now or datetime.now(timezone.utc)
    row = {"pc_time_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    for col in COLUMNS[1:]:
        value = obj.get(col)
        row[col] = "" if value is None else value
    return row


def open_csv(path):
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    f = open(path, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=COLUMNS)
    if new:
        writer.writeheader()
        f.flush()
    return f, writer


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--out", default="data/raw/serial_log.csv")
    args = ap.parse_args()

    import serial  # pyserial; içe aktarma burada, parse_line testleri pyserial'sız çalışsın diye

    f, writer = open_csv(args.out)
    print(f"Kayıt: {args.out} (durdurmak için Ctrl+C)")
    count = 0
    try:
        while True:
            try:
                with serial.Serial(args.port, args.baud, timeout=2) as ser:
                    print(f"Bağlandı: {args.port}")
                    while True:
                        raw = ser.readline()
                        if not raw:
                            continue
                        text = raw.decode("utf-8", errors="replace")
                        obj = parse_line(text)
                        if obj is None:
                            if text.startswith("#"):
                                print(text.strip())
                            continue
                        writer.writerow(to_row(obj))
                        f.flush()
                        count += 1
                        print(
                            f"[{count}] seq={obj.get('seq')} soil_raw={obj.get('soil_raw')} "
                            f"temp={obj.get('temp_c')} err={obj.get('err')}"
                        )
            except serial.SerialException as exc:
                print(f"Seri port hatası: {exc}. 5 sn sonra tekrar denenecek.", file=sys.stderr)
                time.sleep(5)
    except KeyboardInterrupt:
        print("\nDurduruldu.")
    finally:
        f.close()


if __name__ == "__main__":
    main()
