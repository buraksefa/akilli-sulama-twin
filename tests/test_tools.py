"""tools/ altındaki betiklerin donanımsız, ağsız birim testleri.
Çalıştırma (proje kökünden): python -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import era5_download  # noqa: E402
import qc_report  # noqa: E402
import serial_logger  # noqa: E402
import thingspeak_fetch  # noqa: E402


class SerialLoggerTests(unittest.TestCase):
    def test_parse_valid_line(self):
        obj = serial_logger.parse_line('{"node":"node01","seq":3,"soil_raw":512,"temp_c":null}\n')
        self.assertEqual(obj["seq"], 3)
        self.assertIsNone(obj["temp_c"])

    def test_ignores_status_and_broken_lines(self):
        self.assertIsNone(serial_logger.parse_line("# WiFi baglandi"))
        self.assertIsNone(serial_logger.parse_line('{"seq":1,"soil_raw":'))
        self.assertIsNone(serial_logger.parse_line('{"foo":1}'))
        self.assertIsNone(serial_logger.parse_line(""))

    def test_null_becomes_empty_cell(self):
        row = serial_logger.to_row(
            {"seq": 1, "temp_c": None, "soil_raw": 500},
            now=datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(row["temp_c"], "")
        self.assertEqual(row["soil_raw"], 500)
        self.assertEqual(row["pc_time_utc"], "2026-10-08T12:00:00Z")

    def test_csv_header_written_once(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.csv")
            f, w = serial_logger.open_csv(path)
            w.writerow(serial_logger.to_row({"seq": 1}))
            f.close()
            f, w = serial_logger.open_csv(path)
            w.writerow(serial_logger.to_row({"seq": 2}))
            f.close()
            with open(path, encoding="utf-8") as fh:
                lines = fh.read().strip().splitlines()
            self.assertEqual(len(lines), 3)  # 1 başlık + 2 satır


class FakeResponse:
    def __init__(self, feeds):
        self._feeds = feeds

    def raise_for_status(self):
        pass

    def json(self):
        return {"feeds": self._feeds}


class FakeSession:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(dict(params or {}))
        return FakeResponse(self.pages.pop(0))


def make_feed(entry_id, ts):
    return {
        "created_at": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entry_id": entry_id,
        "field1": "500",
        "field2": "50.0",
        "field3": "22.0",
        "field4": "40.0",
        "field5": "0",
        "field6": "-60",
        "field7": str(entry_id),
        "field8": "0",
    }


class ThingSpeakTests(unittest.TestCase):
    def test_paginates_backwards_and_dedupes(self):
        base = datetime(2026, 10, 1, tzinfo=timezone.utc)
        n = thingspeak_fetch.PAGE_SIZE
        # İkinci sayfa en yeni sayfanın en eski kaydıyla örtüşüyor (dedupe testi)
        page1 = [make_feed(1000 + i, base + timedelta(minutes=10000 + i)) for i in range(n)]
        page2 = [make_feed(1000 + i - 3, base + timedelta(minutes=10000 + i - 3)) for i in range(0, 5)]
        session = FakeSession([page1, page2])
        since = base
        rows = thingspeak_fetch.fetch_all("123", since, session=session)
        ids = [r["entry_id"] for r in rows]
        self.assertEqual(ids, sorted(set(ids)))
        self.assertEqual(len(session.calls), 2)
        self.assertNotIn("end", session.calls[0])
        self.assertIn("end", session.calls[1])

    def test_since_filter(self):
        base = datetime(2026, 10, 5, tzinfo=timezone.utc)
        feeds = [make_feed(1, base - timedelta(days=2)), make_feed(2, base + timedelta(hours=1))]
        rows = thingspeak_fetch.fetch_all("123", base, session=FakeSession([feeds]))
        self.assertEqual([r["entry_id"] for r in rows], [2])

    def test_write_csv_maps_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ts.csv")
            feed = make_feed(7, datetime(2026, 10, 8, tzinfo=timezone.utc))
            feed["field3"] = None
            thingspeak_fetch.write_csv(path, [feed])
            with open(path, encoding="utf-8") as fh:
                header, row = fh.read().strip().splitlines()
            self.assertEqual(header.split(",")[:4], ["created_at", "entry_id", "soil_raw", "soil_pct"])
            self.assertEqual(row.split(",")[4], "")  # temp_c boş


class Era5Tests(unittest.TestCase):
    def test_month_range_crosses_year(self):
        self.assertEqual(
            era5_download.month_range("2025-11", "2026-02"), [(2025, 11), (2025, 12), (2026, 1), (2026, 2)]
        )

    def test_request_shape(self):
        req = era5_download.build_request(2025, 3, era5_download.DEFAULT_AREA)
        self.assertEqual(req["month"], "03")
        self.assertEqual(len(req["time"]), 24)
        self.assertEqual(len(req["day"]), 31)
        self.assertEqual(req["data_format"], "netcdf")


class QcTests(unittest.TestCase):
    def build_csv(self, path):
        import pandas as pd

        start = datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc)
        rows = []
        seq = 0
        for i in range(200):
            if 80 <= i < 90:  # 10 kayıtlık kesinti
                continue
            seq = seq + 1 if i != 150 else 1  # i=150'de yeniden başlatma
            soil = 600 + (i % 7)
            if 100 <= i < 140:  # donmuş toprak değeri
                soil = 777
            if i == 50:  # sıçrama
                soil = 1000
            rows.append(
                {
                    "pc_time_utc": (start + timedelta(seconds=60 * i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "seq": seq,
                    "soil_raw": soil,
                    "soil_pct": 50.0,
                    "temp_c": 22.0 + (i % 3) * 0.1,
                    "hum_pct": 40.0 + (i % 5),
                    "err": 1 if i == 10 else 0,
                }
            )
        pd.DataFrame(rows).to_csv(path, index=False)

    def test_detects_problems(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.csv")
            self.build_csv(path)
            df = qc_report.load(path)
            gaps = qc_report.find_gaps(df, 60)
            self.assertEqual(len(gaps), 1)
            self.assertAlmostEqual(gaps["seconds"].iloc[0], 660, delta=1)
            self.assertEqual(len(qc_report.find_restarts(df)), 1)
            runs = qc_report.flatline_runs(df["soil_raw"], 30)
            self.assertEqual(len(runs), 1)
            self.assertIn(df.index[df["soil_raw"] == 1000][0], list(qc_report.spikes(df["soil_raw"])))
            # Düzenli, küçük dalgalanmalı sıcaklık serisinde yanlış alarm olmamalı
            self.assertEqual(len(qc_report.spikes(df["temp_c"])), 0)


if __name__ == "__main__":
    unittest.main()
