"""Zon içi farklılık deneyi: güvenlik payı, sensör yerleşimi ve zon boyutu (sanal dünya).

Soru: zon ortalamasına göre sulama, sığ köklü / kurak hücreleri strese sokuyor. Üç kaldıraç karşılaştırılır:

- **Güvenlik payı** (`margin`): JIT hedefi margin · RAW_nominal; küçük pay = daha erken ve daha çok sulama.
- **Sensör yerleşimi**: `random` (zon içinde rastgele hücre) ya da `critical` (zonun yaz ortasında RAW'a en önce
  inen hücresi). `critical`, kritik noktanın keşifle bilindiğini varsayar; bu yüzden yerleşimin iyimser ucudur.
- **Zon boyutu** (`zone_blocks`): park ızgarası bx × by bloğa bölünür, zon = blok × bitki türü. Daha küçük zon =
  daha çok vana ve (zon başına sensör sayısı sabit olduğundan) daha çok sensör.

Karşılaştırma ölçütü `ORACLE`: gizli hücre durumunu ve bugünün gerçek havasını bilen, zon başına tek doz veren
kâhin (margin 1,0). Verilen zon düzeninde stressiz sulamanın alt sınırıdır; zon içi farklılığın su bedelini ölçer.

Tüm sayılar sanal dünya sonucudur (etiket `synthetic_world` + hava kaynağı); gerçek park ölçümü değildir.
"""

import copy
from typing import Iterable, Optional, Sequence

import pandas as pd

from twin.config import TwinConfig
from twin.sim.virtual_world import build_world, run_world, summarize_run


def world_variant(spec: dict, zone_blocks: Sequence[int], sensor_placement: str) -> dict:
    """Senaryonun yalnız zon düzeni ve sensör yerleşimi değiştirilmiş kopyası (dünya alanları aynı kalır)."""
    s = copy.deepcopy(spec)
    s["zone_blocks"] = [int(zone_blocks[0]), int(zone_blocks[1])]
    s["sensor_placement"] = sensor_placement
    return s


def heterogeneity_experiment(
    spec: dict,
    geojson_path: str,
    weather: pd.DataFrame,
    zone_blocks_list: Iterable[Sequence[int]] = ((1, 1), (2, 2), (3, 3), (4, 4)),
    placements: Iterable[str] = ("random", "critical"),
    margins: Iterable[float] = (0.9, 0.7, 0.5, 0.3),
    sensor_strategies: Iterable[str] = ("SENSOR", "ENKF"),
    seeds: Iterable[int] = range(10),
    config: Optional[TwinConfig] = None,
    qc_options: Iterable[bool] = (False,),
) -> pd.DataFrame:
    """Her zon düzeni × yerleşim × pay × strateji × tohum için bir satır.

    MODEL kestiricisi sensör görmez; yerleşimden ve tohumdan bağımsızdır, bu yüzden düzen ve pay başına bir kez
    koşulur. ORACLE düzen başına bir kez (margin 1,0) koşulur.
    """
    seeds, margins, placements, qc_options = list(seeds), list(margins), list(placements), list(qc_options)
    rows = []

    def add(world, run, layout, placement, strategy, margin, seed, qc=False):
        rows.append(
            {
                "zon_duzeni": f"{layout[0]}x{layout[1]}",
                "zon_sayisi": len(world.zones),
                "sensor_sayisi": len(world.sensors),
                "yerlesim": placement,
                "strateji": strategy,
                "qc": qc,
                "pay": margin,
                "tohum": seed,
                **summarize_run(run),
                "kaynak": f"synthetic_world+{run.source}",
            }
        )

    for layout in zone_blocks_list:
        base = build_world(world_variant(spec, layout, "random"), geojson_path)
        add(
            base,
            run_world(base, weather, "ORACLE", margin=1.0, config=config),
            layout,
            "-",
            "ORACLE",
            1.0,
            -1,
        )
        for m in margins:
            add(base, run_world(base, weather, "MODEL", margin=m, config=config), layout, "-", "MODEL", m, -1)
        for placement in placements:
            world = (
                base
                if placement == "random"
                else build_world(world_variant(spec, layout, placement), geojson_path)
            )
            for strat in sensor_strategies:
                for m in margins:
                    for qc in qc_options:
                        for seed in seeds:
                            r = run_world(
                                world, weather, strat, margin=m, sensor_seed=seed, config=config, qc=qc
                            )
                            add(world, r, layout, placement, strat, m, seed, qc)
    return pd.DataFrame(rows)


def summarize_experiment(df: pd.DataFrame) -> pd.DataFrame:
    """Tohum ortalaması; su, aynı zon düzenindeki kâhine oranla da verilir."""
    keys = ["zon_duzeni", "zon_sayisi", "sensor_sayisi", "yerlesim", "strateji", "qc", "pay"]
    g = (
        df.groupby(keys, sort=False)
        .agg(
            su_m3=("su_m3", "mean"),
            su_m3_std=("su_m3", "std"),
            stresli_alan_ort_pct=("stresli_alan_ort_pct", "mean"),
            stresli_alan_std=("stresli_alan_ort_pct", "std"),
            stresli_alan_maks_pct=("stresli_alan_maks_pct", "mean"),
            derin_sizma_m3=("derin_sizma_m3", "mean"),
            tohum_sayisi=("tohum", "nunique"),
            kaynak=("kaynak", "first"),
        )
        .reset_index()
    )
    oracle = g[g["strateji"] == "ORACLE"].set_index("zon_duzeni")["su_m3"]
    g["su_kahine_orani"] = g["su_m3"] / g["zon_duzeni"].map(oracle)
    return g


def qc_detection(
    spec: dict,
    geojson_path: str,
    weather: pd.DataFrame,
    zone_blocks_list: Iterable[Sequence[int]] = ((1, 1), (2, 2), (3, 3), (4, 4)),
    placements: Iterable[str] = ("random", "critical"),
    margins: Iterable[float] = (0.9, 0.3),
    sensor_strategies: Iterable[str] = ("SENSOR", "ENKF"),
    seeds: Iterable[int] = range(10),
    config: Optional[TwinConfig] = None,
) -> pd.DataFrame:
    """QC açıkken her sensör-sezon için: gerçek arıza türü, yakalandı mı, ilk ret günü, arızanın başladığı gün."""
    rows = []
    for layout in zone_blocks_list:
        for placement in placements:
            world = build_world(world_variant(spec, layout, placement), geojson_path)
            for strat in sensor_strategies:
                for m in margins:
                    for seed in seeds:
                        sd = run_world(
                            world, weather, strat, margin=m, sensor_seed=seed, config=config, qc=True
                        ).sensors
                        sd = sd.assign(day=sd.groupby("sensor_id").cumcount())
                        for sid, g in sd.groupby("sensor_id"):
                            rej = g[~g["qc_reason"].isin(["ok", "nodata"])]
                            act = g[g["fault_active"]]
                            rows.append(
                                {
                                    "zon_duzeni": f"{layout[0]}x{layout[1]}",
                                    "yerlesim": placement,
                                    "strateji": strat,
                                    "pay": m,
                                    "tohum": seed,
                                    "sensor_id": sid,
                                    "ariza": g["fault_type"].iloc[0],
                                    "yakalandi": len(rej) > 0,
                                    "ilk_ret_gunu": rej["day"].min() if len(rej) else float("nan"),
                                    "ariza_baslangic_gunu": act["day"].min() if len(act) else float("nan"),
                                    "ret_nedenleri": ",".join(sorted(set(rej["qc_reason"]))),
                                }
                            )
    return pd.DataFrame(rows)
