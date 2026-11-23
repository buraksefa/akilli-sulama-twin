"""Platform bileşenlerini kuran yardımcılar (CLI, panel ve testler ortak kullanır)."""

import logging
import os
import time
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from twin.config import TwinConfig
from twin.data.forecast import fetch_open_meteo_daily
from twin.devices.ingest import Ingestor
from twin.devices.registry import REGISTRY_PATH, Device, load_registry
from twin.devices.simulator import DeviceSimulator
from twin.sim.virtual_world import World, build_world, load_world_spec

TZ = ZoneInfo("Europe/Istanbul")
log = logging.getLogger("twin.devices")
SPEC_PATH = Path("data/scenarios/yildiz_dunya.json")
GEOJSON = Path("data/public/parks.geojson")


def load_world(root: Path = Path("."), world_seed: Optional[int] = None) -> World:
    spec = load_world_spec(root / SPEC_PATH)
    if world_seed is not None:
        spec["world_seed"] = int(world_seed)
    return build_world(spec, root / GEOJSON)


WEATHER_CACHE = Path(os.environ.get("TWIN_WEATHER_CACHE", "data/devices/weather_cache.pkl"))


@lru_cache(maxsize=4)
def _open_meteo(day_key: str) -> pd.DataFrame:
    era5 = TwinConfig().era5
    last_err = None
    for attempt in range(3):
        try:
            wx = fetch_open_meteo_daily(float(era5.yildiz_lat.value), float(era5.yildiz_lon.value))
            try:
                WEATHER_CACHE.parent.mkdir(parents=True, exist_ok=True)
                wx.to_pickle(WEATHER_CACHE)
            except OSError:
                pass
            return wx
        except Exception as e:  # ağ/servis hatası: bekle ve yeniden dene
            last_err = e
            time.sleep(2 * (attempt + 1))
    if WEATHER_CACHE.exists():
        wx = pd.read_pickle(WEATHER_CACHE)
        if wx.index.max().date() >= datetime.now(TZ).date():
            log.warning("Open-Meteo erişilemedi (%s); diskteki son hava verisi kullanılıyor", last_err)
            wx.attrs["source"] = "open_meteo_cache"
            return wx
    _open_meteo.cache_clear()
    raise RuntimeError(f"Open-Meteo erişilemedi ve kullanılabilir önbellek yok: {last_err}")


def open_meteo_provider() -> pd.DataFrame:
    """Günde bir kez Open-Meteo (92 gün geçmiş + 7 gün tahmin); aynı gün içinde önbellekten.

    Servis geçici olarak yanıt vermezse 3 kez dener, sonra diskteki son başarılı veriyi (bugünü kapsıyorsa) kullanır.
    """
    try:
        return _open_meteo(datetime.now(TZ).date().isoformat())
    except RuntimeError:
        _open_meteo.cache_clear()
        raise


def make_simulator(
    world: World,
    devices: Optional[List[Device]] = None,
    weather_provider=open_meteo_provider,
    seed: int = 0,
    margin: float = 0.9,
) -> DeviceSimulator:
    devices = devices if devices is not None else load_registry(REGISTRY_PATH)
    return DeviceSimulator(world, devices, weather_provider, margin=margin, seed=seed)


def backfill(sim: DeviceSimulator, ingestor: Ingestor, start: datetime, end: datetime, step_s: int) -> int:
    """Simülatörü `start`–`end` arasında adım adım koşup iletileri doğrudan alıma verir (aracısız).

    Panel demosu ve testler içindir; canlı hatta aynı iletiler MQTT üzerinden gelir.
    """
    n = 0
    t = start
    while t <= end:
        for msg in sim.readings(t):
            payload = msg.model_dump_json(by_alias=True, exclude_none=True).encode()
            ingestor.handle(f"sulama/{msg.node}/telemetry", payload, received=int(t.timestamp()))
            n += 1
        t += timedelta(seconds=step_s)
    ingestor.check_offline(int(end.timestamp()))
    return n
