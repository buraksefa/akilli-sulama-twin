"""Sanal parkın 3B (eğik bakışlı) haritası: pydeck / deck.gl.

Gerçek Yıldız Korusu konumunda, açık sokak altlığı (Carto, anahtar gerektirmez) üstünde:

- zonlar bitki türüne göre hafif yükseltilmiş bloklar; renk toprak nemi durumu (ya da bitki / sulama sistemi),
- ağaçlık hücrelerde alçak poligonlu ağaçlar, sensörler direk olarak (renk: QC kararı),
- zon adı etiketleri, seçili zonun kalın çerçevesi ve park sınırı.

Bütün iç dağılım sanal dünya varsayımıdır; yalnız sınır ve konum gerçektir (İBB poligonu).
"""

import re
from typing import Dict, List, Optional, Sequence

import numpy as np
import pydeck as pdk

STATE_RGB = [
    (93, 173, 226),
    (139, 214, 140),
    (247, 205, 90),
    (226, 96, 86),
]  # Nemli, Uygun, Sulama gerekli, Stres
VEG_RGB = {
    "turf": (150, 222, 140),
    "tree": (88, 160, 104),
    "shrub": (214, 196, 110),
    "flower": (240, 156, 190),
}
SYSTEM_RGB = {"yağmurlama": (126, 184, 240), "damla": (110, 206, 186)}
# blok yüksekliği [m] (yalnız görsel): çim alçak, çalı ve çiçek tarhı biraz yüksek
VEG_HEIGHT = {"turf": 0.4, "tree": 0.6, "shrub": 1.6, "flower": 1.0}
NAVY = (22, 38, 74)
TREE_DENSITY = 0.22  # ağaçlık hücrelerin kaçında ağaç çizilir (yalnız görsel)
SENSOR_RGB = {
    "ok": (46, 160, 67),
    "reject": (207, 34, 46),
    "nodata": (140, 140, 140),
    "plain": (255, 255, 255),
}


TIP_LINES = 4


def _tip(html: str) -> Dict[str, str]:
    """deck.gl balonu alan değerlerini düz metin olarak ekler; HTML'i satırlara bölüp etiketleri atar."""
    parts = [re.sub(r"<[^>]+>", "", p).strip() for p in re.split(r"<br\s*/?>", html or "")]
    parts = [p for p in parts if p][:TIP_LINES]
    parts += [""] * (TIP_LINES - len(parts))
    return {f"t{i}": p for i, p in enumerate(parts)}


def _runs(world, key: np.ndarray):
    """Aynı satırda yan yana, aynı anahtarlı hücreleri dikdörtgen şeritlere birleştirir (veri boyutunu küçültür)."""
    order = np.lexsort((world.cell_rc[:, 1], world.cell_rc[:, 0]))
    out = []
    start = prev = order[0]
    for i in order[1:]:
        same_row = world.cell_rc[i, 0] == world.cell_rc[prev, 0]
        adjacent = world.cell_rc[i, 1] == world.cell_rc[prev, 1] + 1
        if same_row and adjacent and key[i] == key[prev]:
            prev = i
            continue
        out.append((start, prev))
        start = prev = i
    out.append((start, prev))
    return out


def _rect(world, a: int, b: int) -> List[list]:
    g = float(world.spec["grid_m"]) / 2
    r, c0, c1 = world.cell_rc[a, 0], world.cell_rc[a, 1], world.cell_rc[b, 1]
    x0, x1 = world.x[c0] - g, world.x[c1] + g
    y0, y1 = world.y[r] - g, world.y[r] + g
    lon, lat = world.to_lonlat(np.array([x0, x1, x1, x0]), np.array([y0, y0, y1, y1]))
    return [[float(lo), float(la)] for lo, la in zip(lon, lat)]


def _zone_outline(world, zi: int, z: float) -> List[list]:
    """Zonun dış kenarlarını çizgi parçaları olarak döndürür (her parça [[lon,lat,z],[lon,lat,z]])."""
    grid = world.to_grid((world.zone_c == zi).astype(float))
    grid = np.nan_to_num(grid, nan=0.0) > 0.5
    pad = np.pad(grid, 1)
    g = float(world.spec["grid_m"]) / 2
    segs = []
    rows, cols = np.nonzero(grid)
    for r, c in zip(rows, cols):
        x, y = world.x[c], world.y[r]
        for dr, dc, (xa, ya, xb, yb) in (
            (0, -1, (x - g, y - g, x - g, y + g)),
            (0, 1, (x + g, y - g, x + g, y + g)),
            (-1, 0, (x - g, y - g, x + g, y - g)),
            (1, 0, (x - g, y + g, x + g, y + g)),
        ):
            if not pad[r + 1 + dr, c + 1 + dc]:
                lon, lat = world.to_lonlat(np.array([xa, xb]), np.array([ya, yb]))
                segs.append([[float(lon[0]), float(lat[0]), z], [float(lon[1]), float(lat[1]), z]])
    return segs


def park_deck(
    world,
    zone_html: Sequence[str],
    zone_title: Sequence[str],
    cell_class: Optional[np.ndarray] = None,
    color_by: str = "state",
    selected: Optional[int] = None,
    sensor_status: Optional[Dict[str, str]] = None,
    sensor_html: Optional[Dict[str, str]] = None,
    label_min_area_m2: float = 6000.0,
) -> pdk.Deck:
    """3B park sahnesi.

    `cell_class`: hücre başına durum sınıfı 0–3 (color_by="state" için). `zone_html`: zonun açıklama balonu (HTML).
    `zone_title`: etikette görünen kısa metin. `sensor_status`: sensör_id → ok / reject / nodata.
    """
    n = len(world.veg_c)
    if color_by == "state":
        cls = np.nan_to_num(np.asarray(cell_class, dtype=float), nan=1.0).astype(int)
        colors = np.array([STATE_RGB[k] for k in cls])
        key = world.zone_c * 10 + cls
    elif color_by == "system":
        colors = np.array([SYSTEM_RGB[world.zones[zi].irrigation] for zi in world.zone_c])
        key = world.zone_c * 10
    else:
        colors = np.array([VEG_RGB[world.zones[zi].veg] for zi in world.zone_c])
        key = world.zone_c * 10

    blocks = []
    for a, b in _runs(world, key):
        zi = int(world.zone_c[a])
        z = world.zones[zi]
        h = VEG_HEIGHT.get(z.veg, 0.5)
        shade = 1.0 if selected is None or zi == selected else 0.78
        blocks.append(
            {
                "polygon": _rect(world, a, b),
                "elev": h,
                "color": [int(v * shade + 255 * (1 - shade)) for v in colors[a]] + [255],
                "zi": zi,
                **_tip(zone_html[zi]),
            }
        )

    # ağaçlar: ağaçlık hücrelerde, tohumla sabit konum ve boy (görsel)
    rng = np.random.default_rng(int(world.spec.get("world_seed", 0)))
    tree_cells = np.flatnonzero(np.array([world.zones[zi].veg == "tree" for zi in world.zone_c]))
    keep = rng.random(n) < TREE_DENSITY  # görsel: her hücreye ağaç koymak zonları örter
    tree_cells = tree_cells[keep[tree_cells]]
    g = float(world.spec["grid_m"])
    jx = rng.uniform(-0.3, 0.3, n) * g
    jy = rng.uniform(-0.3, 0.3, n) * g
    tall = rng.uniform(4.0, 7.5, n)
    tone = rng.integers(0, 3, n)
    greens = [(46, 125, 70), (64, 145, 80), (84, 160, 90)]
    tx = world.x[world.cell_rc[tree_cells, 1]] + jx[tree_cells]
    ty = world.y[world.cell_rc[tree_cells, 0]] + jy[tree_cells]
    tlon, tlat = world.to_lonlat(tx, ty)
    trees = [
        {
            "pos": [float(lo), float(la)],
            "elev": float(tall[c]),
            "color": list(greens[tone[c]]) + [255],
            "zi": int(world.zone_c[c]),
            **_tip(zone_html[int(world.zone_c[c])]),
        }
        for lo, la, c in zip(tlon, tlat, tree_cells)
    ]

    # sensör direkleri
    sensors = []
    for s in world.sensors:
        sid = s.sensor.sensor_id
        stt = (sensor_status or {}).get(sid, "plain")
        lon, lat = world.to_lonlat(s.sensor.pos[0], s.sensor.pos[1])
        sensors.append(
            {
                "pos": [float(lon), float(lat)],
                "color": list(SENSOR_RGB.get(stt, SENSOR_RGB["plain"])) + [255],
                "zi": int(s.zone_index),
                **_tip((sensor_html or {}).get(sid, f"Sensör {sid}")),
            }
        )

    # zon etiketleri (büyük zonlar ve seçili zon)
    labels = []
    for zi, z in enumerate(world.zones):
        if z.area_m2 < label_min_area_m2 and zi != selected:
            continue
        cells = world.cell_rc[world.zone_c == zi]
        cx, cy = world.x[cells[:, 1]].mean(), world.y[cells[:, 0]].mean()
        # ağırlık merkezi zonun dışına düşerse zondaki en yakın hücreye taşı
        d = (world.x[cells[:, 1]] - cx) ** 2 + (world.y[cells[:, 0]] - cy) ** 2
        k = int(np.argmin(d))
        lon, lat = world.to_lonlat(world.x[cells[k, 1]], world.y[cells[k, 0]])
        labels.append(
            {
                "pos": [float(lon), float(lat), 16.0],
                "text": zone_title[zi],
                "zi": zi,
                **_tip(zone_html[zi]),
                "size": 17 if zi == selected else 14,
            }
        )

    ring = world.boundary_xy[0]
    blon, blat = world.to_lonlat(ring[:, 0], ring[:, 1])
    boundary = [{"path": [[float(a), float(b)] for a, b in zip(blon, blat)]}]
    ground = [{"polygon": [[float(a), float(b)] for a, b in zip(blon, blat)]}]

    layers = [
        pdk.Layer(
            "PolygonLayer",
            id="ground",
            data=ground,
            get_polygon="polygon",
            get_fill_color=[214, 236, 205, 200],
            stroked=False,
            pickable=False,
        ),
        pdk.Layer(
            "PolygonLayer",
            id="zones",
            data=blocks,
            get_polygon="polygon",
            get_fill_color="color",
            get_elevation="elev",
            extruded=False,  # yükseltilmiş blok ışıklandırmayla renkleri koyulaştırıyordu; düz zemin + 3B ağaç/sensör
            stroked=False,
            pickable=True,
            auto_highlight=True,
            highlight_color=[255, 255, 255, 90],
        ),
        pdk.Layer(
            "ColumnLayer",
            id="trees",
            data=trees,
            get_position="pos",
            get_elevation="elev",
            get_fill_color="color",
            radius=2.6,
            disk_resolution=6,
            opacity=0.92,
            extruded=True,
            pickable=True,
        ),
        pdk.Layer(
            "PathLayer",
            id="boundary",
            data=boundary,
            get_path="path",
            get_color=[40, 90, 50],
            width_min_pixels=2,
            pickable=False,
        ),
    ]
    if selected is not None:
        layers.append(
            pdk.Layer(
                "LineLayer",
                id="selected",
                data=[{"s": s[0], "t": s[1]} for s in _zone_outline(world, selected, 2.2)],
                get_source_position="s",
                get_target_position="t",
                get_color=list(NAVY),
                get_width=4,
                width_min_pixels=3,
                pickable=False,
            )
        )
    layers += [
        pdk.Layer(
            "ColumnLayer",
            id="sensors",
            data=sensors,
            get_position="pos",
            get_elevation=6,
            get_fill_color="color",
            radius=1.6,
            disk_resolution=8,
            extruded=True,
            pickable=True,
        ),
        pdk.Layer(
            "TextLayer",
            id="labels",
            data=labels,
            get_position="pos",
            get_text="text",
            get_size="size",
            get_color=list(NAVY) + [255],
            background=True,
            get_background_color=[255, 255, 255, 235],
            background_padding=[6, 3, 6, 3],
            get_border_color=list(NAVY) + [80],
            get_border_width=1,
            font_family='"Source Sans Pro", "Helvetica Neue", Arial, sans-serif',
            font_weight=600,
            character_set=pdk.types.String("auto"),  # düz dize; aksi halde ifade sanılır (Türkçe harfler)
            billboard=True,
            pickable=True,
        ),
    ]

    lon_c, lat_c = world.to_lonlat(float(np.mean(ring[:, 0])), float(np.mean(ring[:, 1])))
    view = pdk.ViewState(
        longitude=float(lon_c), latitude=float(lat_c), zoom=15.9, pitch=50, bearing=-24, max_pitch=70
    )
    return pdk.Deck(
        layers=layers,
        initial_view_state=view,
        map_provider="carto",
        map_style=pdk.map_styles.CARTO_LIGHT,
        tooltip={
            "html": "<b>{t0}</b><br/>{t1}<br/>{t2}<br/><span style='opacity:.7'>{t3}</span>",
            "style": {
                "backgroundColor": "white",
                "color": "#1f2a44",
                "fontSize": "13px",
                "borderRadius": "8px",
                "boxShadow": "0 2px 10px rgba(0,0,0,.18)",
                "padding": "8px 10px",
            },
        },
    )


def picked_zone(event, layer_ids=("zones", "trees", "labels", "sensors")) -> Optional[int]:
    """st.pydeck_chart seçim olayından tıklanan zonun dizinini döndürür."""
    try:
        objs = event["selection"]["objects"]
    except (KeyError, TypeError):
        try:
            objs = event.selection.objects
        except AttributeError:
            return None
    for lid in layer_ids:
        for o in (objs or {}).get(lid, []) or []:
            if isinstance(o, dict) and "zi" in o:
                return int(o["zi"])
    return None
