"""Sanal park: fiziksel kuruluma geçmeden önce dijital test alanı.

Bir senaryo dosyası (data/scenarios/*.json) parkı zonlara böler; her zonun bitki profili, alanı ve
sanal sensörleri vardır. Simülatör her gün, her zon için:
1. sanal sensörler gerçek toprak nemini (Dr_{t-1}) gürültü ve arıza modeliyle okur,
2. seçilen strateji bir sulama ÖNERİSİ üretir (aktüatör/MQTT komutu yok, onay Burak'ta),
3. FAO-56 kova modeli zonu bir gün ilerletir.

Kurum verisi geldikçe değişen tek şey senaryo dosyası ve config parametreleridir.
Kaynağı doğrulanmış bitki profili olmayan zon (ör. ağaç) simüle edilmez, `status` ile işaretlenir.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from twin.config import VEGETATION_PROFILES, TwinConfig, config_for_vegetation
from twin.model.kc import get_stage_based_kc
from twin.model.waterbalance import (
    compute_raw,
    compute_taw,
    depletion_to_vwc,
    simulate_water_balance_step,
)
from twin.sim.strategies import IrrigationStrategy

THETA_PHYSICAL_MAX = 0.60  # fault_injection.py ile aynı fiziksel üst sınır [m3/m3]


@dataclass
class SensorFault:
    """Sanal sensör arıza modeli (gün bazlı, durumlu)."""

    type: str = "none"  # none, bias, drift, freeze, dropout
    value: float = 0.0  # bias [m3/m3]
    rate_per_day: float = 0.0  # drift [m3/m3/gün]
    start_day: int = 0  # freeze başlangıcı (sezon günü)
    duration_days: int = 0  # freeze süresi
    prob: float = 0.0  # dropout olasılığı


@dataclass
class VirtualSensor:
    """Zondaki tek bir sanal toprak nemi sensörü."""

    sensor_id: str
    pos: List[float]
    noise_std: float
    fault: SensorFault = field(default_factory=SensorFault)
    _frozen: Optional[float] = None

    def read(self, true_theta: float, day: int, rng: np.random.Generator) -> float:
        """Gerçek nemden sensör okuması üretir; okuma yoksa NaN."""
        f = self.fault
        value = true_theta + rng.normal(0.0, self.noise_std)
        if f.type == "bias":
            value += f.value
        elif f.type == "drift":
            value += f.rate_per_day * day
        elif f.type == "freeze" and f.start_day <= day < f.start_day + f.duration_days:
            if self._frozen is None:
                self._frozen = value
            return float(self._frozen)
        elif f.type == "dropout" and rng.random() < f.prob:
            return float("nan")
        return float(np.clip(value, 0.0, THETA_PHYSICAL_MAX))

    def is_faulty(self, day: int) -> bool:
        f = self.fault
        if f.type in ("bias", "drift"):
            return True
        if f.type == "freeze":
            return f.start_day <= day < f.start_day + f.duration_days
        return f.type == "dropout"


@dataclass
class Zone:
    zone_id: str
    name: str
    vegetation: str
    area_m2: float
    area_source: str
    layout: List[float]
    sensors: List[VirtualSensor]

    @property
    def has_verified_profile(self) -> bool:
        return self.vegetation in VEGETATION_PROFILES


@dataclass
class Scenario:
    name: str
    park_id: str
    status: str
    notes: str
    canvas: List[float]
    zones: List[Zone]


def load_scenario(path: str | Path) -> Scenario:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    zones = []
    for z in data["zones"]:
        sensors = [
            VirtualSensor(
                sensor_id=s["sensor_id"],
                pos=s["pos"],
                noise_std=float(s["noise_std"]),
                fault=SensorFault(**s.get("fault", {})),
            )
            for s in z.get("sensors", [])
        ]
        zones.append(
            Zone(
                zone_id=z["zone_id"],
                name=z["name"],
                vegetation=z["vegetation"],
                area_m2=float(z["area_m2"]),
                area_source=z.get("area_source", "belirtilmedi"),
                layout=z["layout"],
                sensors=sensors,
            )
        )
    return Scenario(
        name=data["name"],
        park_id=data["park_id"],
        status=data.get("status", "assumption"),
        notes=data.get("notes", ""),
        canvas=data.get("canvas", [100, 60]),
        zones=zones,
    )


@dataclass
class ParkRun:
    """Simülasyon sonucu: zon-gün ve sensör-gün tabloları."""

    zones: pd.DataFrame
    sensors: pd.DataFrame
    skipped: Dict[str, str]
    source: str


def simulate_virtual_park(
    scenario: Scenario,
    weather_df: pd.DataFrame,
    strategy_factory: Callable[[str], IrrigationStrategy],
    base_config: Optional[TwinConfig] = None,
    seed: int = 0,
    forecast_rain_noise_std: float = 1.0,
) -> ParkRun:
    """Tüm zonları gün gün ilerletir.

    strategy_factory(zone_id) her zon için yeni (durumlu) bir strateji örneği döndürür.
    Zonun kontrol girdisi, geçerli sensör okumalarının ortalamasıdır (hepsi NaN ise None).
    Strateji ayrıca gerçek Dr_{t-1}'i görür (S2/S5 gibi model tabanlı stratejiler için;
    engine.simulate_strategy_season ile aynı sözleşme).
    """
    rng = np.random.default_rng(seed)
    zone_rows, sensor_rows, skipped = [], [], {}
    dates = weather_df.index
    n = len(weather_df)

    for zone in scenario.zones:
        if not zone.has_verified_profile:
            skipped[zone.zone_id] = f"'{zone.vegetation}' için doğrulanmış bitki profili yok"
            continue
        cfg = config_for_vegetation(zone.vegetation, base_config)
        theta_fc = float(cfg.soil.theta_fc.value)
        theta_wp = float(cfg.soil.theta_wp.value)
        zr = float(cfg.soil.root_depth_m.value)
        p = float(cfg.soil.p_depletion.value)
        eff = float(cfg.irrigation.efficiency.value)
        runoff = float(cfg.soil.runoff_threshold_mm.value)
        taw = compute_taw(theta_fc, theta_wp, zr)
        raw = compute_raw(taw, p)

        strategy = strategy_factory(zone.zone_id)
        for s in zone.sensors:
            s._frozen = None
        dr = 0.0
        for i in range(n):
            w = weather_df.iloc[i]
            date = dates[i]
            true_theta = depletion_to_vwc(dr, theta_fc, zr)

            readings = []
            for s in zone.sensors:
                r = s.read(true_theta, i, rng)
                readings.append(r)
                sensor_rows.append(
                    {
                        "time": date,
                        "zone_id": zone.zone_id,
                        "sensor_id": s.sensor_id,
                        "theta_true": true_theta,
                        "theta_read": r,
                        "fault_type": s.fault.type,
                        "fault_active": s.is_faulty(i),
                    }
                )
            valid = [r for r in readings if not np.isnan(r)]
            obs = float(np.mean(valid)) if valid else None

            kc = get_stage_based_kc(date.month, crop_params=cfg.crop)
            w_row = w.copy()
            w_row["kc"] = kc
            next_rain = float(weather_df["rain_mm"].iloc[i + 1]) if i + 1 < n else 0.0
            forecast = max(0.0, next_rain + rng.normal(0.0, forecast_rain_noise_std))

            dose = strategy.decide(i, date, w_row, dr, obs, forecast, cfg)
            state = simulate_water_balance_step(
                dr_prev_mm=dr,
                eto_mm=float(w["eto_mm"]),
                kc=kc,
                precip_mm=float(w["rain_mm"]),
                irrigation_mm=dose,
                theta_fc=theta_fc,
                theta_wp=theta_wp,
                root_depth_m=zr,
                p_depletion=p,
                irr_efficiency=eff,
                runoff_thresh_mm=runoff,
            )
            zone_rows.append(
                {
                    "time": date,
                    "zone_id": zone.zone_id,
                    "eto_mm": float(w["eto_mm"]),
                    "rain_mm": float(w["rain_mm"]),
                    "kc": kc,
                    "dr_start_mm": dr,
                    "theta_start": true_theta,
                    "sensor_obs": obs if obs is not None else np.nan,
                    "advice_gross_mm": dose,
                    "advice_m3": dose / 1000.0 * zone.area_m2,
                    "depletion_mm": state.depletion_mm,
                    "theta_vwc": state.theta_vwc,
                    "ks": state.ks,
                    "eta_mm": state.eta_mm,
                    "dp_mm": state.dp_mm,
                    "ro_mm": state.ro_mm,
                    "taw_mm": taw,
                    "raw_mm": raw,
                    "theta_fc": theta_fc,
                    "theta_wp": theta_wp,
                }
            )
            dr = state.depletion_mm

    return ParkRun(
        zones=pd.DataFrame(zone_rows),
        sensors=pd.DataFrame(sensor_rows),
        skipped=skipped,
        source=weather_df.attrs.get("source", "unknown"),
    )


def parameter_inventory(scenario: Scenario, base_config: Optional[TwinConfig] = None) -> pd.DataFrame:
    """Simülasyonda kullanılan parametrelerin kaynak ve durum listesi (kurum verisi takibi için)."""
    rows = []
    for z in scenario.zones:
        rows.append(
            {
                "kapsam": z.zone_id,
                "parametre": "area_m2",
                "değer": z.area_m2,
                "kaynak": z.area_source,
                "durum": scenario.status,
            }
        )
        if not z.has_verified_profile:
            rows.append(
                {
                    "kapsam": z.zone_id,
                    "parametre": "vegetation",
                    "değer": z.vegetation,
                    "kaynak": "doğrulanmış profil yok; simüle edilmiyor",
                    "durum": "missing",
                }
            )
            continue
        cfg = config_for_vegetation(z.vegetation, base_config)
        items = {
            "kc_initial": cfg.crop.kc_initial,
            "kc_mid": cfg.crop.kc_mid,
            "kc_end": cfg.crop.kc_end,
            "root_depth_m": cfg.soil.root_depth_m,
            "p_depletion": cfg.soil.p_depletion,
            "theta_fc": cfg.soil.theta_fc,
            "theta_wp": cfg.soil.theta_wp,
            "irrigation_efficiency": cfg.irrigation.efficiency,
            "runoff_threshold_mm": cfg.soil.runoff_threshold_mm,
        }
        for k, it in items.items():
            rows.append(
                {
                    "kapsam": z.zone_id,
                    "parametre": k,
                    "değer": it.value,
                    "kaynak": it.source,
                    "durum": it.status.value,
                }
            )
    return pd.DataFrame(rows)
