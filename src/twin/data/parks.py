"""Park poligonları ve sulama bölgeleri (zones) veri yükleyicisi.

Kaynak: İBB Açık Veri Portalı (data/public/parks.geojson).
Sözleşme: docs/INTERFACES.md ve docs/DATA_INVENTORY.md.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class IrrigationZone:
    """Park içerisindeki bir sulama bölgesi (zone)."""

    zone_id: str
    park_id: str
    veg_type: str  # lawn, meadow, flower, shrub, tree, mixed
    irrigation_type: str  # sprinkler, drip, none
    area_m2: float
    app_rate_mm_h: float = 10.0
    valve_id: Optional[str] = None
    controller_id: Optional[str] = None
    water_source: str = "unknown"  # network, well, reclaimed, tank, unknown
    irrigated_fraction: float = 0.60

    def to_dict(self) -> Dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "park_id": self.park_id,
            "veg_type": self.veg_type,
            "irrigation_type": self.irrigation_type,
            "area_m2": self.area_m2,
            "app_rate_mm_h": self.app_rate_mm_h,
            "valve_id": self.valve_id,
            "controller_id": self.controller_id,
            "water_source": self.water_source,
            "irrigated_fraction": self.irrigated_fraction,
        }


@dataclass
class Park:
    """Park metadata ve poligon geometrisi."""

    id: str
    name: str
    area_m2: float
    centroid_lon: float
    centroid_lat: float
    tur: str = "Park"
    ilce: str = "BEŞİKTAŞ"
    geometry: Optional[Dict[str, Any]] = None
    zones: List[IrrigationZone] = field(default_factory=list)

    def total_irrigated_area_m2(self) -> float:
        """Toplam sulanan alanı hesaplar."""
        if not self.zones:
            return self.area_m2 * 0.60
        return sum(z.area_m2 for z in self.zones)


def load_parks(geojson_path: Optional[str | Path] = None) -> Dict[str, Park]:
    """parks.geojson dosyasını okuyup Park nesneleri sözlüğü döndürür.

    Dosya bulunamazsa varsayılan Yıldız ve Maçka parklarını döner.
    """
    if geojson_path is None:
        geojson_path = (
            Path(__file__).resolve().parent.parent.parent.parent / "data" / "public" / "parks.geojson"
        )

    p_path = Path(geojson_path)
    if not p_path.exists():
        # Fallback dictionary if file is not found
        return {
            "yildiz": Park("yildiz", "YILDIZ PARKI", 389760.0, 29.0142, 41.0494),
            "macka": Park("macka", "MAÇKA DEMOKRASİ PARKI", 139419.0, 28.993131, 41.044271),
        }

    with open(p_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    parks: Dict[str, Park] = {}
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        pid = props.get("id") or props.get("name", "").lower().replace(" ", "_")
        name = props.get("name", pid)
        area = float(props.get("area_m2", 0.0))
        lon = float(props.get("centroid_lon", 0.0))
        lat = float(props.get("centroid_lat", 0.0))
        tur = props.get("tur", "Park")
        ilce = props.get("ilce", "BEŞİKTAŞ")
        geom = feature.get("geometry")

        park = Park(
            id=pid,
            name=name,
            area_m2=area,
            centroid_lon=lon,
            centroid_lat=lat,
            tur=tur,
            ilce=ilce,
            geometry=geom,
        )

        # Varsayılan tek bölge ekle (DATA_INVENTORY.md gereği)
        default_zone = IrrigationZone(
            zone_id=f"{pid}_zone_01",
            park_id=pid,
            veg_type="lawn",
            irrigation_type="sprinkler",
            area_m2=area * 0.60,
            app_rate_mm_h=10.0,
            water_source="unknown",
            irrigated_fraction=0.60,
        )
        park.zones.append(default_zone)
        parks[pid] = park

    return parks


def get_default_zones(park_id: str, geojson_path: Optional[str | Path] = None) -> List[IrrigationZone]:
    """Belirli bir park için sulama bölgelerini getirir."""
    parks = load_parks(geojson_path)
    if park_id in parks:
        return parks[park_id].zones
    return [
        IrrigationZone(
            zone_id=f"{park_id}_default",
            park_id=park_id,
            veg_type="lawn",
            irrigation_type="sprinkler",
            area_m2=10000.0,
            app_rate_mm_h=10.0,
            water_source="unknown",
            irrigated_fraction=0.60,
        )
    ]
