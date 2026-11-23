"""Sanal sensör düğümleri: sanal parkı gerçek zamanda yürütür ve firmware ile aynı telemetriyi üretir.

Akış:

1. **Gün başı (`prepare`)**: Open-Meteo geçmiş + tahmin havasıyla sanal dünya bugüne getirilir
   (`plan_from_forecast`, ikiz: model + sensör, QC açık). Sonuç: her hücrenin bu sabahki su açığı ve ikizin
   bugün için önerdiği zon dozları. Sanal parkta bu öneri sanal sulama sistemine uygulanır (CLAUDE.md §2.3:
   gerçek aktüatöre ve `cmd` konusuna hiçbir şey gitmez).
2. **Gün içi (`readings`)**: hücre açığı saat saat ilerler. ETc gündüz (06–19) sinüs biçiminde dağıtılır, yağış
   güne eşit yayılır, sulama `sim_irrigation_hour` saatinde verilir. Her düğüm kendi hücresini okur. Gürültü ve
   arıza (kayma, donma, veri kaybı) sanal dünyadaki sensör modelinden gelir. Ham değer firmware kalibrasyonunun
   tersiyle üretilir; VWC ve yüzde firmware gibi hamdan hesaplanır.
3. Sıcaklık ve nem günlük en düşük/en yüksek sıcaklıktan basit bir gün içi eğriyle türetilir (varsayım, `sim`).

Bütün değerler `sim: true` etiketlidir; gerçek ölçüm değildir.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from twin.config import TwinConfig
from twin.devices.registry import Device
from twin.devices.schema import Telemetry, raw_to_pct, raw_to_vwc, vwc_to_raw
from twin.sim.virtual_world import World, _stage_index, plan_from_forecast

WeatherProvider = Callable[[], pd.DataFrame]


def daylight_fraction(hour: float, start: float = 6.0, end: float = 19.0) -> float:
    """Günlük ETc'nin saat `hour`a kadar gerçekleşen payı (gündüz sinüs eğrisi, 0–1)."""
    if hour <= start:
        return 0.0
    if hour >= end:
        return 1.0
    return 0.5 * (1.0 - math.cos(math.pi * (hour - start) / (end - start)))


def diurnal_temp(hour: float, tmin: float, tmax: float) -> float:
    """En düşük 06:00, en yüksek 15:00 kosinüs eğrisi (varsayım)."""
    if 6.0 <= hour <= 15.0:
        x = (hour - 6.0) / 9.0
        return tmin + (tmax - tmin) * 0.5 * (1 - math.cos(math.pi * x))
    h = hour - 15.0 if hour > 15.0 else hour + 9.0
    x = h / 15.0
    return tmax - (tmax - tmin) * 0.5 * (1 - math.cos(math.pi * x))


@dataclass
class _NodeState:
    seq: int = 0
    rssi: float = -65.0
    rssi_base: float = -65.0  # düğümün konumuna bağlı ortalama sinyal
    battery_v: float = 4.15
    started: Optional[datetime] = None
    day_error: float = 0.0  # bugünkü sensör hatası (günde bir çekilir)
    prev_error: Optional[float] = None  # dünkü hata; gün içinde dünküden bugünküne doğrusal geçilir
    day_missing: bool = False  # veri kaybı günü


@dataclass
class DeviceSimulator:
    world: World
    devices: List[Device]
    weather_provider: WeatherProvider
    config: TwinConfig = field(default_factory=TwinConfig)
    margin: float = 0.9
    strategy: str = "ENKF"
    seed: int = 0
    # gün başı durumu
    day: Optional[pd.Timestamp] = None
    weather_source: str = "unknown"
    _dr0: Optional[np.ndarray] = None
    _dose_z: Optional[np.ndarray] = None
    _today: Optional[pd.Series] = None
    _day_index: int = 0
    _nodes: Dict[str, _NodeState] = field(default_factory=dict)

    def __post_init__(self):
        self._rng = np.random.default_rng(self.seed)
        by_id = {s.sensor.sensor_id: s for s in self.world.sensors}
        self._sensors = {
            d.node: by_id[d.node] for d in self.devices if d.source == "simulated" and d.node in by_id
        }
        missing = [d.node for d in self.devices if d.source == "simulated" and d.node not in by_id]
        if missing:
            raise ValueError(f"Kayıttaki sanal düğümler dünyada yok: {missing}")

    @property
    def simulated_nodes(self) -> List[str]:
        return list(self._sensors)

    def prepare(self, today: pd.Timestamp) -> None:
        """Dünyayı bugünün sabahına getirir ve ikizin bugünkü zon dozlarını alır."""
        day = pd.Timestamp(today).normalize()
        wx = self.weather_provider().copy()
        self.weather_source = str(wx.attrs.get("source", "unknown"))
        # hedef günden önceki günler "geçmiş" sayılır (geçmiş bir günü yeniden üretirken de aynı akış)
        attrs = dict(wx.attrs)
        wx["is_forecast"] = wx.index >= day
        wx.attrs = attrs
        if wx.loc[~wx["is_forecast"], ["eto_mm", "rain_mm"]].isna().any().any():
            raise ValueError("Hedef günden önceki havada boş gün var")
        run, plan = plan_from_forecast(
            self.world,
            wx,
            self.strategy,
            margin=self.margin,
            sensor_seed=self.seed,
            config=self.config,
            qc=True,
        )
        fc = wx[wx["is_forecast"]]
        if day not in fc.index:
            raise ValueError(f"Hava verisinde bugünün ({day.date()}) tahmini yok")
        self._today = fc.loc[day]
        today_plan = plan[plan["time"] == day].set_index("zone")
        self._dose_z = np.array([float(today_plan.loc[z.zone_id, "dose_mm"]) for z in self.world.zones])
        self._dr0 = run.dr_end.copy()
        self._day_index = len(run.dates)
        self.day = day
        # günlük sensör hatası: sanal dünyanın sensör modeli (gürültü + arıza) sabah okumasına uygulanır
        for node, ws in self._sensors.items():
            st = self._node(node)
            theta0 = self.cell_theta(ws.cell, 0.0)
            r = ws.sensor.read(theta0, self._day_index, self._rng)
            st.prev_error = None if st.day_missing else st.day_error if st.seq else None
            st.day_missing = bool(np.isnan(r))
            st.day_error = 0.0 if st.day_missing else float(r - theta0)

    def _node(self, node: str) -> _NodeState:
        if node not in self._nodes:
            base = float(self._rng.uniform(-80, -55))
            self._nodes[node] = _NodeState(rssi=base, rssi_base=base)
        return self._nodes[node]

    def cell_theta(self, cell: int, hour: float) -> float:
        """Hücrenin saat `hour`daki hacimsel nemi (gün içi ilerletme)."""
        w, cfg = self.world, self.config
        zi = int(w.zone_c[cell])
        taw, raw, p = w.taw_c[cell], w.raw_c[cell], w.p_c[cell]
        dr0 = float(self._dr0[cell])
        ks = 1.0 if dr0 <= raw else max(0.0, (taw - dr0) / ((1 - p) * taw))
        eto = float(self._today["eto_mm"])
        etc = ks * w.kc_c[cell, _stage_index(self.day.month)] * w.micro_c[cell] * eto
        rain = float(self._today["rain_mm"])
        runoff = float(cfg.soil.runoff_threshold_mm.value)
        p_net = rain - max(0.0, rain - runoff)
        irr = (
            w.zones[zi].efficiency * self._dose_z[zi]
            if hour >= cfg.devices.sim_irrigation_hour.value
            else 0.0
        )
        dr = dr0 + etc * daylight_fraction(hour) - p_net * hour / 24.0 - irr
        dr = float(np.clip(dr, 0.0, taw))
        return float(w.fc_c[cell] - dr / (1000.0 * w.zr_c[cell]))

    def readings(self, now: datetime) -> List[Telemetry]:
        """`now` anında yayın yapan sanal düğümlerin ölçümleri (veri kaybı yaşayan düğüm yayın yapmaz)."""
        ts = pd.Timestamp(now)
        local_day = (ts.tz_localize(None) if ts.tzinfo else ts).normalize()
        if self.day is None or local_day != self.day:
            self.prepare(local_day)
        hour = ts.hour + ts.minute / 60.0
        dev = self.config.devices
        out = []
        tmin = float(self._today.get("temp_min", np.nan))
        tmax = float(self._today.get("temp_max", np.nan))
        for node, ws in self._sensors.items():
            st = self._node(node)
            if st.started is None:
                st.started = now
            if st.day_missing:
                continue  # veri kaybı günü: düğüm yayın yapmaz
            theta = self.cell_theta(ws.cell, hour)
            # gece yarısı sıçraması olmasın: hata dünküden bugünküne gün boyunca doğrusal geçer
            err = (
                st.day_error
                if st.prev_error is None
                else st.prev_error + (st.day_error - st.prev_error) * hour / 24
            )
            reading = float(
                np.clip(theta + err + self._rng.normal(0, dev.sim_short_noise_vwc.value), 0.0, 0.6)
            )
            raw = vwc_to_raw(reading, dev)
            days_up = (now - st.started).total_seconds() / 86400.0
            st.seq += 1
            st.rssi = float(np.clip(0.8 * st.rssi + 0.2 * st.rssi_base + self._rng.normal(0, 1.5), -95, -45))
            st.battery_v = 4.15 - dev.sim_battery_drain_v_per_day.value * days_up + self._rng.normal(0, 0.005)
            temp = diurnal_temp(hour, tmin, tmax) if np.isfinite(tmin) and np.isfinite(tmax) else None
            hum = None
            if temp is not None and tmax > tmin:
                hum = float(
                    np.clip(85.0 - 35.0 * (temp - tmin) / (tmax - tmin) + self._rng.normal(0, 2), 20, 100)
                )
            out.append(
                Telemetry(
                    node=node,
                    seq=st.seq,
                    up=int(days_up * 86400),
                    ts=int(ts.timestamp()),
                    soil_raw=raw,
                    soil_pct=round(raw_to_pct(raw, dev), 1),
                    soil_vwc=round(raw_to_vwc(raw, dev), 3),
                    temp_c=None if temp is None else round(temp + self._rng.normal(0, 0.3), 1),
                    hum_pct=None if hum is None else round(hum, 1),
                    pump_s=None,
                    rssi=int(round(st.rssi)),
                    err=0,
                    battery_v=round(st.battery_v, 3),
                    sim=True,
                )
            )
        return out
