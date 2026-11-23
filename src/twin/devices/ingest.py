"""Telemetri alımı: MQTT iletisini doğrular, depoya yazar, kalite kontrolünü uygular ve uyarı üretir.

Gerçek ve sanal düğüm aynı yoldan geçer. Uyarılar yalnız bildirimdir; hiçbir sulama komutu üretilmez.

- **Anlık kontrol** (her ileti): şema, kayıtta olmayan düğüm, firmware hata bitleri, fiziksel aralık.
- **Günlük QC** (gün değişince, düğüm başına): günün ortalama VWC'si `twin.qc.online.OnlineSensorQC`'ye verilir
  (aralık, kesinti, eksik oranı, donmuş değer, tarla kapasitesi üstü). Kayma testi (kural 7) açık döngü model
  referansı ister; canlı hatta bu referans henüz bağlı değil, bu yüzden burada çalışmaz.
- **Uyarılar**: çevrimdışı, düşük pil, zayıf sinyal, cihaz hatası, QC reddi, kayıtsız düğüm.
"""

import json
import time
from datetime import datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import numpy as np
from pydantic import ValidationError

from twin.config import TwinConfig
from twin.devices.registry import Device
from twin.devices.schema import Telemetry, err_text, parse_topic
from twin.devices.store import TelemetryStore
from twin.qc.online import QC_REASONS, OnlineSensorQC

TZ = ZoneInfo("Europe/Istanbul")
ALERT_TEXT = {
    "offline": "Düğüm çevrimdışı",
    "battery_low": "Düşük pil",
    "rssi_weak": "Zayıf sinyal",
    "device_error": "Cihaz hata bildirdi",
    "qc_reject": "Kalite kontrol okumayı reddetti",
    "unknown_device": "Kayıtta olmayan düğüm",
    "bad_payload": "Geçersiz ileti",
}


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts, TZ).date().isoformat()


class Ingestor:
    def __init__(self, store: TelemetryStore, devices: List[Device], config: Optional[TwinConfig] = None):
        self.store = store
        self.cfg = config or TwinConfig()
        self.devices: Dict[str, Device] = {d.node: d for d in devices}
        self.theta_fc = 0.28  # ikizin bildiği nominal θFC (yildiz_dunya.json soil.theta_fc.mean)
        self._qc: Dict[str, OnlineSensorQC] = {}
        self._buf: Dict[str, tuple] = {}  # düğüm → (gün, [vwc...])
        self._last_day: Dict[str, str] = {}
        self.rebuild_qc()

    # ------------------------------------------------------------- QC durumu
    def _qc_for(self, node: str) -> OnlineSensorQC:
        if node not in self._qc:
            self._qc[node] = OnlineSensorQC(self.theta_fc, self.cfg.sensor_qc)
        return self._qc[node]

    def rebuild_qc(self) -> None:
        """Yeniden başlatmada günlük QC durumunu depodaki günlük ortalamalardan yeniden kurar."""
        qd = self.store.qc_daily()
        for node, g in qd.groupby("node"):
            q = self._qc_for(node)
            prev = None
            for r in g.itertuples():
                if prev is not None:  # aradaki boş günler okuma yok sayılır
                    gap = (np.datetime64(r.day) - np.datetime64(prev)).astype(int) - 1
                    for _ in range(max(gap, 0)):
                        q.update(float("nan"))
                q.update(float(r.vwc_mean) if r.n else float("nan"))
                prev = r.day
            self._last_day[node] = prev
        # henüz kapanmamış günün okumalarını tampona geri yükle (yeniden başlatmada günlük ortalama eksik kalmasın)
        rd = self.store.readings()
        if len(rd):
            rd = rd.assign(day=rd["ts"].map(_day))
            for node, g in rd.groupby("node"):
                last_day = g["day"].max()
                if self._last_day.get(node) is not None and last_day <= self._last_day[node]:
                    continue
                ok = g[(g["day"] == last_day) & (g["live_qc"] == "ok")]
                self._buf[node] = (last_day, list(ok["soil_vwc"].astype(float)))

    def _close_day(self, node: str, day: str, values: list) -> str:
        q = self._qc_for(node)
        last = self._last_day.get(node)
        if last is not None:
            gap = (np.datetime64(day) - np.datetime64(last)).astype(int) - 1
            for _ in range(max(gap, 0)):
                q.update(float("nan"))
        mean = float(np.mean(values)) if values else float("nan")
        _, reason = q.update(mean)
        self.store.set_qc_daily(node, day, None if np.isnan(mean) else mean, len(values), reason)
        self._last_day[node] = day
        return reason

    # ------------------------------------------------------------- iletiler
    def handle(self, topic: str, payload: bytes, received: Optional[int] = None) -> Optional[str]:
        """Bir MQTT iletisini işler; sonuç kodunu döndürür (stored/duplicate/status/rejected/ignored)."""
        received = int(received if received is not None else time.time())
        try:
            node, kind = parse_topic(topic)
        except ValueError:
            return "ignored"
        if kind == "status":
            state = payload.decode("utf-8", "replace").strip().lower()
            if state in ("online", "offline"):
                self.store.set_status(node, state, received)
                if state == "offline":
                    self.store.open_alert(node, "offline", "Düğüm çevrimdışı olduğunu bildirdi", received)
                else:
                    self.store.close_alert(node, "offline", received)
            return "status"
        if kind != "telemetry":
            return "ignored"
        try:
            t = Telemetry.model_validate(json.loads(payload))
        except (ValueError, ValidationError) as e:
            self.store.open_alert(
                node, "bad_payload", f"{ALERT_TEXT['bad_payload']}: {str(e)[:120]}", received
            )
            return "rejected"
        if t.node != node:
            self.store.open_alert(node, "bad_payload", "İletideki düğüm adı konuyla uyuşmuyor", received)
            return "rejected"
        if node not in self.devices:
            self.store.open_alert(node, "unknown_device", ALERT_TEXT["unknown_device"], received)
        ts = t.ts if t.ts > 0 else received

        qcp = self.cfg.sensor_qc
        live = "ok"
        if t.err:
            live = "device_error"
        elif t.soil_vwc is None or not (qcp.vwc_min.value <= t.soil_vwc <= qcp.vwc_max.value):
            live = "range"
        row = {
            "node": node,
            "ts": ts,
            "received": received,
            "seq": t.seq,
            "soil_raw": t.soil_raw,
            "soil_vwc": t.soil_vwc,
            "soil_pct": t.soil_pct,
            "temp_c": t.temp_c,
            "hum_pct": t.hum_pct,
            "rssi": t.rssi,
            "battery_v": t.battery_v,
            "err": t.err,
            "sim": int(t.sim),
            "live_qc": live,
        }
        if not self.store.add_reading(row):
            return "duplicate"

        # günlük QC: gün değişince önceki günü kapat
        day = _day(ts)
        buf_day, vals = self._buf.get(node, (day, []))
        if buf_day != day:
            reason = self._close_day(node, buf_day, vals)
            self._alert_qc(node, reason, received)
            vals = []
        if live == "ok":
            vals.append(t.soil_vwc)
        self._buf[node] = (day, vals)

        self._alerts_for(node, t, received)
        self.store.close_alert(node, "offline", received)
        return "stored"

    def _alert_qc(self, node: str, reason: str, when: int):
        if reason in ("ok", "nodata"):
            self.store.close_alert(node, "qc_reject", when)
        else:
            self.store.open_alert(node, "qc_reject", f"Günlük QC: {QC_REASONS.get(reason, reason)}", when)

    def _alerts_for(self, node: str, t: Telemetry, when: int):
        """Eşik altına inince açılır, eşik + histerezis üstüne çıkınca kapanır."""
        d = self.cfg.devices
        checks = []
        if t.battery_v is not None:
            checks.append(
                (
                    "battery_low",
                    t.battery_v < d.battery_low_v.value,
                    t.battery_v >= d.battery_low_v.value + d.alert_hysteresis_v.value,
                    f"{t.battery_v} V",
                )
            )
        if t.rssi is not None:
            checks.append(
                (
                    "rssi_weak",
                    t.rssi < d.rssi_weak_dbm.value,
                    t.rssi >= d.rssi_weak_dbm.value + d.alert_hysteresis_db.value,
                    f"{t.rssi} dBm",
                )
            )
        checks.append(("device_error", bool(t.err), not t.err, err_text(t.err)))
        for kind, bad, good, detail in checks:
            if bad:
                self.store.open_alert(node, kind, f"{ALERT_TEXT[kind]}: {detail}", when)
            elif good:
                self.store.close_alert(node, kind, when)

    def check_offline(self, now: Optional[int] = None) -> List[str]:
        """Son ölçümü `offline_after_intervals` aralıktan eski kayıtlı düğümler için çevrimdışı uyarısı açar."""
        now = int(now if now is not None else time.time())
        d = self.cfg.devices
        limit = d.offline_after_intervals.value * d.report_interval_s.value
        latest = self.store.latest().set_index("node")["received"] if len(self.store.latest()) else {}
        out = []
        for node in self.devices:
            last = latest.get(node) if hasattr(latest, "get") else None
            if last is None or now - int(last) > limit:
                msg = (
                    "Hiç ölçüm gelmedi"
                    if last is None
                    else f"Son ölçüm {int((now - int(last)) / 60)} dk önce"
                )
                if self.store.open_alert(node, "offline", f"{ALERT_TEXT['offline']}: {msg}", now):
                    out.append(node)
        return out
