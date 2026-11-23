"""Düğüm telemetri sözleşmesi: firmware (`firmware/sulama_node`) ile sanal düğüm aynı JSON'u yayınlar.

Konular (bkz. server/mosquitto/config/acl):

- `sulama/<node>/telemetry`  JSON ölçüm (aşağıdaki alanlar)
- `sulama/<node>/status`     "online" / "offline" (retained, son vasiyet)

Bu paket `cmd` konusuna hiçbir zaman yayın yapmaz (CLAUDE.md §2.3): `topic_for` yalnız izinli türleri üretir.

Firmware alanları (buildJson): node, seq, up, ts, soil_raw, soil_pct, soil_vwc, temp_c, hum_pct, pump_s, rssi, err.
Ek ve isteğe bağlı alanlar: `battery_v` (pil gerilimi), `sim` (sanal düğüm bayrağı), `schema`.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from twin.config import DeviceParameters

SCHEMA = "sulama.telemetry/1"
TOPIC_ROOT = "sulama"
PUBLISH_KINDS = ("telemetry", "status")  # cmd ve ack bilinçli olarak yok

# firmware hata bitleri (sulama_node.ino)
ERR_DHT, ERR_SOIL, ERR_WIFI, ERR_UPLOAD, ERR_MQTT = 1, 2, 4, 8, 16
ERR_TEXT = {
    ERR_DHT: "sıcaklık/nem sensörü okunamadı",
    ERR_SOIL: "toprak sensörü uç değer",
    ERR_WIFI: "Wi-Fi yok",
    ERR_UPLOAD: "ikincil yükleme başarısız",
    ERR_MQTT: "MQTT yayını başarısız",
}


class Telemetry(BaseModel):
    """Bir düğüm ölçümü. Bilinmeyen alanlar korunur (ileri uyumluluk)."""

    model_config = ConfigDict(extra="allow")

    node: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    seq: int = Field(ge=0)
    up: Optional[int] = None  # çalışma süresi [s]
    ts: int = Field(ge=0, description="Unix zamanı [s]; düğüm saati yoksa 0")
    soil_raw: Optional[int] = None
    soil_pct: Optional[float] = None
    soil_vwc: Optional[float] = None
    temp_c: Optional[float] = None
    hum_pct: Optional[float] = None
    pump_s: Optional[float] = None
    rssi: Optional[int] = None
    err: int = 0
    battery_v: Optional[float] = None
    sim: bool = False
    schema_id: str = Field(default=SCHEMA, alias="schema")


def topic_for(node: str, kind: str) -> str:
    if kind not in PUBLISH_KINDS:
        raise ValueError(f"Yayın türü {kind!r} izinli değil; izinli: {PUBLISH_KINDS} (cmd yayını yapılmaz)")
    if "/" in node or "+" in node or "#" in node:
        raise ValueError(f"Geçersiz düğüm adı: {node!r}")
    return f"{TOPIC_ROOT}/{node}/{kind}"


def parse_topic(topic: str) -> tuple:
    """`sulama/<node>/<kind>` → (node, kind); biçim dışıysa ValueError."""
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != TOPIC_ROOT or not parts[1]:
        raise ValueError(f"Beklenmeyen konu: {topic!r}")
    return parts[1], parts[2]


def vwc_to_raw(vwc: float, p: Optional[DeviceParameters] = None) -> int:
    """firmware rawToVWC() tersine: VWC → kapasitif sensör ham değeri (kalibrasyonsuz doğrusal ilişki)."""
    p = p or DeviceParameters()
    dry, wet, fs = p.soil_raw_dry.value, p.soil_raw_wet.value, p.vwc_full_scale.value
    return int(round(dry - (vwc / fs) * (dry - wet)))


def raw_to_vwc(raw: int, p: Optional[DeviceParameters] = None) -> float:
    p = p or DeviceParameters()
    dry, wet, fs = p.soil_raw_dry.value, p.soil_raw_wet.value, p.vwc_full_scale.value
    return float((dry - raw) / (dry - wet) * fs)


def raw_to_pct(raw: int, p: Optional[DeviceParameters] = None) -> float:
    p = p or DeviceParameters()
    dry, wet = p.soil_raw_dry.value, p.soil_raw_wet.value
    return float(min(100.0, max(0.0, (dry - raw) * 100.0 / (dry - wet))))


def err_text(err: int) -> str:
    return ", ".join(t for bit, t in ERR_TEXT.items() if err & bit) or "yok"
