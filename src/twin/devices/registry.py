"""Cihaz kaydı: hangi düğüm nerede, hangi zonda, sanal mı gerçek mi.

Kayıt `data/devices/registry.json` dosyasıdır ve depoya girer (sır içermez). Gerçek bir sensör bağlandığında
ilgili satırda `source` "real" yapılır ve firmware'e aynı `node` adı verilir; simülatör o düğümü artık yayınlamaz,
ikiz ve panel aynı konudan gerçek veriyi okur.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

SOURCES = ("simulated", "real")
REGISTRY_PATH = Path("data/devices/registry.json")


@dataclass
class Device:
    node: str  # MQTT konu adı: sulama/<node>/telemetry
    name: str
    park: str
    zone: str
    vegetation: str
    lon: float
    lat: float
    source: str = "simulated"
    kind: str = "soil_moisture_node"
    firmware: str = "sulama_node"
    channels: List[str] = field(
        default_factory=lambda: ["soil_raw", "soil_vwc", "temp_c", "hum_pct", "rssi", "battery_v"]
    )
    installed: Optional[str] = None  # kurulum tarihi (gerçek düğüm)
    notes: str = ""

    def __post_init__(self):
        if self.source not in SOURCES:
            raise ValueError(f"{self.node}: source {self.source!r}; seçenekler {SOURCES}")


def load_registry(path: Path = REGISTRY_PATH) -> List[Device]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    devices = [Device(**d) for d in data["devices"]]
    nodes = [d.node for d in devices]
    if len(set(nodes)) != len(nodes):
        raise ValueError("Kayıtta yinelenen düğüm adı var")
    return devices


def save_registry(devices: List[Device], path: Path = REGISTRY_PATH, note: str = "") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "sulama.registry/1",
        "note": note,
        "devices": [asdict(d) for d in devices],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def registry_from_world(world) -> List[Device]:
    """Sanal dünyadaki her sensör için bir sanal düğüm kaydı (konum: gerçek park koordinatı)."""
    out = []
    for s in world.sensors:
        z = world.zones[s.zone_index]
        lon, lat = world.to_lonlat(s.sensor.pos[0], s.sensor.pos[1])
        out.append(
            Device(
                node=s.sensor.sensor_id,
                name=f"{z.label} · {s.sensor.sensor_id.split('-')[-1]}",
                park=world.spec["park_id"],
                zone=z.zone_id,
                vegetation=z.veg,
                lon=round(float(lon), 6),
                lat=round(float(lat), 6),
            )
        )
    return out
