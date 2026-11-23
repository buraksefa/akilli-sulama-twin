"""Telemetri deposu (SQLite): ölçümler, düğüm durumu, günlük QC kararları ve uyarılar.

Yerelde ve sunucuda aynı dosya biçimi kullanılır. Yol `TWIN_DEVICE_DB` ortam değişkeniyle değişir; varsayılan
`data/devices/telemetry.sqlite` (depoya girmez). Grafana için Telegraf → InfluxDB hattı ayrıca çalışır; bu depo
ikiz, QC ve cihaz paneli içindir.
"""

import os
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

DEFAULT_DB = Path("data/devices/telemetry.sqlite")

DDL = """
CREATE TABLE IF NOT EXISTS readings (
    node TEXT NOT NULL,
    ts INTEGER NOT NULL,          -- düğüm zamanı (unix s); düğüm saati yoksa alınış zamanı
    received INTEGER NOT NULL,    -- sunucuya varış (unix s)
    seq INTEGER,
    soil_raw INTEGER,
    soil_vwc REAL,
    soil_pct REAL,
    temp_c REAL,
    hum_pct REAL,
    rssi INTEGER,
    battery_v REAL,
    err INTEGER,
    sim INTEGER,
    live_qc TEXT,                 -- anlık kontrol: ok / range / device_error
    PRIMARY KEY (node, ts, seq)
);
CREATE INDEX IF NOT EXISTS readings_ts ON readings(ts);
CREATE TABLE IF NOT EXISTS node_status (
    node TEXT PRIMARY KEY,
    state TEXT,                   -- online / offline (düğümün kendi bildirdiği)
    updated INTEGER
);
CREATE TABLE IF NOT EXISTS qc_daily (
    node TEXT NOT NULL,
    day TEXT NOT NULL,            -- YYYY-MM-DD (yerel)
    vwc_mean REAL,
    n INTEGER,
    reason TEXT,                  -- twin.qc.online neden kodu
    PRIMARY KEY (node, day)
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT,
    opened INTEGER NOT NULL,
    closed INTEGER                -- NULL: etkin
);
CREATE INDEX IF NOT EXISTS alerts_open ON alerts(node, kind, closed);
"""


def db_path(path: Optional[str] = None) -> Path:
    return Path(path or os.environ.get("TWIN_DEVICE_DB") or DEFAULT_DB)


class TelemetryStore:
    def __init__(self, path: Optional[str] = None, read_only: bool = False):
        self.path = db_path(path)
        if read_only:
            self.conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(self.path, check_same_thread=False)
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript(DDL)
        self.conn.row_factory = sqlite3.Row

    def close(self):
        self.conn.close()

    # ---------------------------------------------------------------- yazma
    def add_reading(self, row: dict) -> bool:
        cols = list(row)
        cur = self.conn.execute(
            f"INSERT OR IGNORE INTO readings ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [row[c] for c in cols],
        )
        self.conn.commit()
        return cur.rowcount > 0

    def set_status(self, node: str, state: str, when: int):
        self.conn.execute(
            "INSERT INTO node_status(node, state, updated) VALUES (?,?,?) "
            "ON CONFLICT(node) DO UPDATE SET state=excluded.state, updated=excluded.updated",
            (node, state, when),
        )
        self.conn.commit()

    def set_qc_daily(self, node: str, day: str, vwc_mean: float, n: int, reason: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO qc_daily(node, day, vwc_mean, n, reason) VALUES (?,?,?,?,?)",
            (node, day, vwc_mean, n, reason),
        )
        self.conn.commit()

    def open_alert(self, node: str, kind: str, message: str, when: int) -> bool:
        """Aynı düğüm ve türde etkin uyarı yoksa açar; açtıysa True."""
        if self.conn.execute(
            "SELECT 1 FROM alerts WHERE node=? AND kind=? AND closed IS NULL", (node, kind)
        ).fetchone():
            return False
        self.conn.execute(
            "INSERT INTO alerts(node, kind, message, opened) VALUES (?,?,?,?)", (node, kind, message, when)
        )
        self.conn.commit()
        return True

    def close_alert(self, node: str, kind: str, when: int) -> int:
        cur = self.conn.execute(
            "UPDATE alerts SET closed=? WHERE node=? AND kind=? AND closed IS NULL", (when, node, kind)
        )
        self.conn.commit()
        return cur.rowcount

    # ---------------------------------------------------------------- okuma
    def readings(self, node: Optional[str] = None, since: Optional[int] = None) -> pd.DataFrame:
        q, args = "SELECT * FROM readings WHERE 1=1", []
        if node:
            q, args = q + " AND node=?", args + [node]
        if since is not None:
            q, args = q + " AND ts>=?", args + [since]
        return pd.read_sql_query(q + " ORDER BY ts", self.conn, params=args)

    def latest(self) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT r.* FROM readings r JOIN (SELECT node, MAX(ts) AS ts FROM readings GROUP BY node) m "
            "ON r.node=m.node AND r.ts=m.ts",
            self.conn,
        )

    def status(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM node_status", self.conn)

    def qc_daily(self, node: Optional[str] = None) -> pd.DataFrame:
        if node:
            return pd.read_sql_query(
                "SELECT * FROM qc_daily WHERE node=? ORDER BY day", self.conn, params=[node]
            )
        return pd.read_sql_query("SELECT * FROM qc_daily ORDER BY node, day", self.conn)

    def alerts(self, active_only: bool = False) -> pd.DataFrame:
        q = (
            "SELECT * FROM alerts"
            + (" WHERE closed IS NULL" if active_only else "")
            + " ORDER BY opened DESC"
        )
        return pd.read_sql_query(q, self.conn)
