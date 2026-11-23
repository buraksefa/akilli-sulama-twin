"""3B park sahnesi: konumlandırma, katmanlar, balon alanları ve tıklama çözümleme."""

import json

import numpy as np

from twin.sim.virtual_world import build_world, load_world_spec
from twin.ui.park3d import _tip, park_deck, picked_zone

SPEC = "data/scenarios/yildiz_dunya.json"
GEOJSON = "data/public/parks.geojson"


def _world():
    return build_world(load_world_spec(SPEC), GEOJSON)


def test_lonlat_roundtrip_inside_istanbul():
    w = _world()
    lon, lat = w.to_lonlat(w.x[w.cell_rc[:, 1]], w.y[w.cell_rc[:, 0]])
    assert 28.9 < lon.min() < lon.max() < 29.1
    assert 41.0 < lat.min() < lat.max() < 41.1


def test_deck_layers_and_size():
    w = _world()
    zt = [f"<b>Z{i}</b><br>satır" for i in range(len(w.zones))]
    d = park_deck(
        w, zt, [f"Z{i}" for i in range(len(w.zones))], cell_class=np.zeros(len(w.veg_c)), selected=0
    )
    j = json.loads(d.to_json())
    ids = {layer["id"] for layer in j["layers"]}
    assert {"zones", "trees", "sensors", "labels", "selected", "boundary"} <= ids
    zones = next(layer for layer in j["layers"] if layer["id"] == "zones")
    assert {b["zi"] for b in zones["data"]} == set(range(len(w.zones)))
    assert len(d.to_json()) < 2_000_000


def test_tip_strips_html():
    t = _tip("<b>Çim 2</b> · Çim<br>ikiz: Uygun<br/>x")
    assert t == {"t0": "Çim 2 · Çim", "t1": "ikiz: Uygun", "t2": "x", "t3": ""}


def test_picked_zone_from_event():
    ev = {"selection": {"indices": {"zones": [3]}, "objects": {"zones": [{"zi": 5}]}}}
    assert picked_zone(ev) == 5
    assert picked_zone({"selection": {"objects": {}}}) is None
    assert picked_zone(None) is None
