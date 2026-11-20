"""Kayma testi kalibrasyonu, adım 1: kayma testi kapalı QC ile günlük okuma-model farkı serilerini toplar.

Kullanım: .venv/bin/python tools/drift_calibration/collect_series.py YIL  (repo kökünden). Kaynak: synthetic_world+era5.
"""

import pickle
import sys
import warnings

import numpy as np

from twin.sim.engine import prepare_season_weather
from twin.sim.heterogeneity import world_variant
from twin.sim.virtual_world import build_world, load_world_spec, run_world

warnings.filterwarnings("ignore")

spec = load_world_spec("data/scenarios/yildiz_dunya.json")
year = int(sys.argv[1])
series = []
w = prepare_season_weather(season_year=year, source="era5", park_id="yildiz")
for layout, pl in [((1, 1), "random"), ((2, 2), "random"), ((3, 3), "critical"), ((4, 4), "critical")]:
    world = build_world(world_variant(spec, layout, pl), "data/public/parks.geojson")
    for strat in ("ENKF", "SENSOR"):
        for seed in range(4):
            run = run_world(world, w, strat, margin=0.7, sensor_seed=seed, qc=True, qc_drift=False)
            sd = run.sensors
            for s in world.sensors:
                tw = run.twins[s.zone_index]
                g = sd[sd.sensor_id == s.sensor.sensor_id]
                series.append(
                    dict(
                        year=year,
                        layout=layout,
                        strat=strat,
                        seed=seed,
                        fault=s.sensor.fault.type,
                        kc=np.array([tw.kc(d.month) for d in w.index]),
                        zr=tw.zr,
                        r=(g.theta_read - g.theta_openloop).values,
                        used=g.used.values,
                        eto=w.eto_mm.values,
                        rain=w.rain_mm.values,
                        dose=run.dose_mm[:, s.zone_index],
                    )
                )
pickle.dump(series, open(f"outputs/sensor_qc_drift/calib/series_{year}.pkl", "wb"))
print(year, len(series))
