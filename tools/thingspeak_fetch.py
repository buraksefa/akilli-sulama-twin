#!/usr/bin/env python3
"""ThingSpeak kanalındaki kayıtları CSV'ye indirir (sunucu çalışmadığı dönemleri tamamlamak için).

ThingSpeak tek istekte en fazla 8000 kayıt verir; script en yeniden geriye doğru sayfalar.
Kanal özelse okuma anahtarını THINGSPEAK_READ_KEY ortam değişkeniyle ver.

Alan eşlemesi (firmware ile aynı): field1 soil_raw, field2 soil_pct, field3 temp_c, field4 hum_pct,
field5 pump_s, field6 rssi, field7 seq, field8 err.

Kullanım:
    python tools/thingspeak_fetch.py --channel 1234567 --since 2026-10-01 --out data/raw/thingspeak.csv
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

FIELD_NAMES = {
    "field1": "soil_raw",
    "field2": "soil_pct",
    "field3": "temp_c",
    "field4": "hum_pct",
    "field5": "pump_s",
    "field6": "rssi",
    "field7": "seq",
    "field8": "err",
}
COLUMNS = ["created_at", "entry_id"] + list(FIELD_NAMES.values())
PAGE_SIZE = 8000


def parse_ts(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def fetch_page(channel, end, read_key=None, session=requests):
    params = {"results": PAGE_SIZE, "timezone": "UTC"}
    if end is not None:
        params["end"] = end.strftime("%Y-%m-%d %H:%M:%S")
    if read_key:
        params["api_key"] = read_key
    resp = session.get(f"https://api.thingspeak.com/channels/{channel}/feeds.json", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("feeds", [])


def fetch_all(channel, since, read_key=None, session=requests):
    """since (UTC datetime) ve sonrasındaki tüm kayıtları eskiden yeniye sıralı döndürür."""
    seen = {}
    end = None
    while True:
        feeds = fetch_page(channel, end, read_key, session)
        if not feeds:
            break
        for feed in feeds:
            seen[feed["entry_id"]] = feed
        earliest = min(parse_ts(f["created_at"]) for f in feeds)
        if len(feeds) < PAGE_SIZE or earliest <= since:
            break
        end = earliest - timedelta(seconds=1)
    rows = [f for f in seen.values() if parse_ts(f["created_at"]) >= since]
    rows.sort(key=lambda f: f["entry_id"])
    return rows


def write_csv(path, feeds):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for feed in feeds:
            row = {"created_at": feed["created_at"], "entry_id": feed["entry_id"]}
            for field, name in FIELD_NAMES.items():
                value = feed.get(field)
                row[name] = "" if value is None else value
            writer.writerow(row)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--channel", required=True, help="ThingSpeak kanal numarası")
    ap.add_argument("--since", required=True, help="YYYY-MM-DD (UTC) ve sonrası")
    ap.add_argument("--out", default="data/raw/thingspeak.csv")
    args = ap.parse_args()

    since = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    feeds = fetch_all(args.channel, since, os.environ.get("THINGSPEAK_READ_KEY"))
    write_csv(args.out, feeds)
    print(f"{len(feeds)} kayıt yazıldı: {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
