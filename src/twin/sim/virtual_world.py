"""Sanal test dünyası: gerçek Yıldız sınırı içinde rastgele üretilmiş heterojen bir park.

Üç katman birbirinden ayrıdır:

1. **Sanal dünya (gerçeğin yerine geçer, modelden gizli):** park poligonu 10 m'lik hücrelere bölünür. Her hücrenin
   bitki türü, toprak su tutma değerleri (θFC, θWP), kök derinliği, bitki katsayısı ve mikroklima çarpanı senaryo
   aralıklarından rastgele (mekânsal olarak yumuşak) çekilir. Dünya ERA5 havasıyla her hücrede FAO-56 kovasını
   gün gün yürütür.
2. **Sanal sensörler:** haritadaki noktalar; yalnız bulundukları hücrenin nemini gürültü ve arızayla ölçer.
3. **Dijital ikiz (sınanan model):** her sulama zonu için yalnız nominal parametreleri, dünün ERA5 değerlerini ve
   zondaki sensör okumalarını görür; zonun toprak su açığını kestirir ve sulama ÖNERİR. Öneri dünyaya uygulanır.

Sonuç ölçütleri dünyadan okunur: su (m³), strese giren alan payı, derin sızma, ikizin kestirim hatası.
Bu dünya bir test ortamıdır; ürettiği sayılar gerçek park ölçümü değildir (etiket: `synthetic_world`).
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from matplotlib.path import Path as MplPath
from scipy.ndimage import gaussian_filter

from twin.config import TwinConfig
from twin.model.assimilation import EnsembleKalmanFilter
from twin.qc.online import OnlineSensorQC
from twin.sim.virtual_park import SensorFault, VirtualSensor

M_PER_DEG_LAT = 110_574.0  # WGS84, 41° enlem civarı yaklaşık değer (yerel düzlem izdüşümü için yeterli)
M_PER_DEG_LON_EQUATOR = 111_320.0
FIELD_SMOOTHING_M = 60.0  # mekânsal rastgele alanların ölçeği (sanal dünya varsayımı)
VEG_KEYS = ["turf", "tree", "shrub", "flower"]
# random: zon içinde rastgele hücre; critical: zonun en önce strese giren hücresi (keşifle bilindiği varsayılır)
SENSOR_PLACEMENTS = ("random", "critical")


def _stage_index(month: int) -> int:
    """model/kc.py ile aynı evre eşlemesi: Nisan-Mayıs ini, Haziran-Ağustos mid, diğer aylar end."""
    if month in (4, 5):
        return 0
    if month in (6, 7, 8):
        return 1
    return 2


def _smooth_field(rng: np.random.Generator, shape, sigma_cells: float) -> np.ndarray:
    """[-1, 1] aralığına ölçeklenmiş, mekânsal olarak yumuşak rastgele alan."""
    f = gaussian_filter(rng.normal(size=shape), sigma=sigma_cells)
    f = f - f.mean()
    return f / max(np.abs(f).max(), 1e-9)


@dataclass
class WorldZone:
    zone_id: str
    veg: str
    label: str
    n_cells: int
    area_m2: float
    efficiency: float
    irrigation: str  # sulama sistemi: yağmurlama / damla
    application_rate_mm_h: float  # sistemin alana su verme hızı
    # ikizin bildiği nominal değerler
    kc_nominal: tuple
    zr_nominal: float
    p_nominal: float


@dataclass
class WorldSensor:
    sensor: VirtualSensor
    zone_index: int
    cell: int  # iç hücre dizinindeki konum


@dataclass
class World:
    spec: dict
    x: np.ndarray  # hücre merkezleri, doğu yönü [m]
    y: np.ndarray  # kuzey yönü [m]
    inside: np.ndarray  # (ny, nx) bool
    cell_rc: np.ndarray  # (n, 2) iç hücrelerin satır/sütun dizini
    veg_c: np.ndarray  # (n,) VEG_KEYS dizini
    zone_c: np.ndarray  # (n,) zon dizini
    fc_c: np.ndarray
    wp_c: np.ndarray
    zr_c: np.ndarray
    p_c: np.ndarray
    kc_c: np.ndarray  # (n, 3) evre bazlı Kc (ini, mid, end)
    micro_c: np.ndarray
    zones: List[WorldZone]
    sensors: List[WorldSensor]
    cell_area_m2: float
    boundary_xy: List[np.ndarray] = field(default_factory=list)

    @property
    def taw_c(self) -> np.ndarray:
        return 1000.0 * (self.fc_c - self.wp_c) * self.zr_c

    @property
    def raw_c(self) -> np.ndarray:
        return self.p_c * self.taw_c

    def to_grid(self, values: np.ndarray) -> np.ndarray:
        """İç hücre değerlerini (ny, nx) ızgarasına yerleştirir; dışarısı NaN."""
        g = np.full(self.inside.shape, np.nan)
        g[self.cell_rc[:, 0], self.cell_rc[:, 1]] = values
        return g


def load_world_spec(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _polygon_rings(geojson_path: Path, park_id: str) -> List[np.ndarray]:
    data = json.loads(geojson_path.read_text(encoding="utf-8"))
    for f in data["features"]:
        if f["properties"].get("id") == park_id:
            geom = f["geometry"]
            if geom["type"] == "Polygon":
                return [np.asarray(r, dtype=float) for r in geom["coordinates"]]
            return [np.asarray(r, dtype=float) for poly in geom["coordinates"] for r in poly]
    raise KeyError(f"'{park_id}' poligonu bulunamadı: {geojson_path}")


def build_world(spec: dict, geojson_path: str | Path) -> World:
    """Senaryo ve park poligonundan sanal dünyayı üretir (world_seed ile belirlenimci)."""
    rings_ll = _polygon_rings(Path(geojson_path), spec["park_id"])
    lon0 = float(np.mean(rings_ll[0][:, 0]))
    lat0 = float(np.mean(rings_ll[0][:, 1]))
    kx = M_PER_DEG_LON_EQUATOR * np.cos(np.radians(lat0))
    rings = [np.column_stack(((r[:, 0] - lon0) * kx, (r[:, 1] - lat0) * M_PER_DEG_LAT)) for r in rings_ll]

    g = float(spec["grid_m"])
    xmin, ymin = rings[0].min(axis=0)
    xmax, ymax = rings[0].max(axis=0)
    x = np.arange(xmin + g / 2, xmax, g)
    y = np.arange(ymin + g / 2, ymax, g)
    xx, yy = np.meshgrid(x, y)
    pts = np.column_stack((xx.ravel(), yy.ravel()))
    inside = MplPath(rings[0]).contains_points(pts)
    for hole in rings[1:]:
        inside &= ~MplPath(hole).contains_points(pts)
    inside = inside.reshape(xx.shape)
    cell_rc = np.argwhere(inside)
    n = len(cell_rc)

    rng = np.random.default_rng(spec["world_seed"])
    sig = FIELD_SMOOTHING_M / g

    def field_at_cells():
        return _smooth_field(rng, inside.shape, sig)[cell_rc[:, 0], cell_rc[:, 1]]

    # bitki dağılımı: önce ağaçlık (yumuşak alanın en yüksek kısmı), kalan açık alan çim/çalı/çiçek
    veg_spec = spec["vegetation"]
    frac = np.array([veg_spec[k]["fraction"] for k in VEG_KEYS], dtype=float)
    frac = frac / frac.sum()
    veg_c = np.empty(n, dtype=int)
    a = field_at_cells()
    order = np.argsort(-a)
    n_tree = int(round(frac[1] * n))
    veg_c[order[:n_tree]] = 1
    rest = order[n_tree:]
    b = field_at_cells()[rest]
    rest = rest[np.argsort(b)]
    open_frac = frac[[0, 2, 3]] / frac[[0, 2, 3]].sum()
    cuts = np.cumsum((open_frac * len(rest)).round().astype(int))[:-1]
    for key_idx, chunk in zip((0, 2, 3), np.split(rest, cuts)):
        veg_c[chunk] = key_idx

    soil = spec["soil"]
    fc_c = soil["theta_fc"]["mean"] + soil["theta_fc"]["spread"] * field_at_cells()
    wp_c = soil["theta_wp"]["mean"] + soil["theta_wp"]["spread"] * field_at_cells()
    mc = soil["microclimate_et_factor"]
    micro_c = mc["min"] + (mc["max"] - mc["min"]) * (field_at_cells() + 1.0) / 2.0

    u_zr = (field_at_cells() + 1.0) / 2.0
    u_kc = (field_at_cells() + 1.0) / 2.0
    zr_c = np.empty(n)
    p_c = np.empty(n)
    kc_c = np.empty((n, 3))
    for i, key in enumerate(VEG_KEYS):
        m = veg_c == i
        vs = veg_spec[key]
        lo, hi = vs["root_depth_m"]
        zr_c[m] = lo + (hi - lo) * u_zr[m]
        p_c[m] = vs["p_depletion"]
        if "kc_stage" in vs:
            kc_c[m] = np.asarray(vs["kc_stage"])
        else:
            klo, khi = vs["kc_range"]
            kc_c[m] = (klo + (khi - klo) * u_kc[m])[:, None]

    # sulama zonları: ızgara blokları × bitki türü
    bx, by = spec["zone_blocks"]
    col_block = np.minimum((cell_rc[:, 1] * bx) // inside.shape[1], bx - 1)
    row_block = np.minimum((cell_rc[:, 0] * by) // inside.shape[0], by - 1)
    block = row_block * bx + col_block
    zones: List[WorldZone] = []
    zone_c = np.empty(n, dtype=int)
    for i, key in enumerate(VEG_KEYS):
        vs = veg_spec[key]
        for blk in range(bx * by):
            m = (veg_c == i) & (block == blk)
            if not m.any():
                continue
            zone_c[m] = len(zones)
            kc_nom = tuple(vs["kc_stage"]) if "kc_stage" in vs else (float(np.mean(vs["kc_range"])),) * 3
            zones.append(
                WorldZone(
                    zone_id=f"{key}-{blk + 1}",
                    veg=key,
                    label=f"{vs['label']} {blk + 1}",
                    n_cells=int(m.sum()),
                    area_m2=float(m.sum() * g * g),
                    efficiency=float(vs["efficiency"]),
                    irrigation=str(vs["irrigation"]),
                    application_rate_mm_h=float(vs["application_rate_mm_h"]),
                    kc_nominal=kc_nom,
                    zr_nominal=float(np.mean(vs["root_depth_m"])),
                    p_nominal=float(vs["p_depletion"]),
                )
            )

    # sensörler: zon başına rastgele hücreler, arıza türü olasılıkla
    sspec = spec["sensors"]
    probs = sspec["fault_probabilities"]
    fault_types = list(probs) + ["none"]
    fault_p = list(probs.values()) + [1.0 - sum(probs.values())]
    placement = spec.get("sensor_placement", "random")
    if placement not in SENSOR_PLACEMENTS:
        raise ValueError(f"sensor_placement {placement!r}; seçenekler: {SENSOR_PLACEMENTS}")
    taw_tmp = 1000.0 * (fc_c - wp_c) * zr_c
    # kritiklik: yaz ortasında tarla kapasitesinden RAW'a kaç günde inildiği (küçük = önce strese girer)
    days_to_raw = p_c * taw_tmp / np.maximum(kc_c[:, 1] * micro_c, 1e-9)
    sensors: List[WorldSensor] = []
    for zi, z in enumerate(zones):
        cells = np.flatnonzero(zone_c == zi)
        k = min(veg_spec[z.veg]["sensors_per_zone"], len(cells))
        chosen = rng.choice(
            cells, size=k, replace=False
        )  # rng her yerleşimde aynı tüketilir (arızalar eşleşir)
        if placement == "critical":
            chosen = cells[np.argsort(days_to_raw[cells], kind="stable")[:k]]
        for j, cell in enumerate(chosen):
            ftype = str(rng.choice(fault_types, p=fault_p))
            fault = SensorFault(type=ftype)
            if ftype == "drift":
                fault.rate_per_day = float(sspec["drift_rate_per_day"])
            elif ftype == "freeze":
                fault.start_day = int(rng.integers(20, 150))
                fault.duration_days = int(sspec["freeze_days"])
            elif ftype == "dropout":
                fault.prob = float(sspec["dropout_prob"])
            r, c = cell_rc[cell]
            sensors.append(
                WorldSensor(
                    VirtualSensor(
                        f"TN-{z.zone_id}-{j + 1}", [float(x[c]), float(y[r])], sspec["noise_std"], fault
                    ),
                    zone_index=zi,
                    cell=int(cell),
                )
            )

    return World(
        spec=spec,
        x=x,
        y=y,
        inside=inside,
        cell_rc=cell_rc,
        veg_c=veg_c,
        zone_c=zone_c,
        fc_c=fc_c,
        wp_c=wp_c,
        zr_c=zr_c,
        p_c=p_c,
        kc_c=kc_c,
        micro_c=micro_c,
        zones=zones,
        sensors=sensors,
        cell_area_m2=g * g,
        boundary_xy=rings,
    )


# ---------------------------------------------------------------------------------------------- dijital ikiz
STRATEGIES: Dict[str, tuple] = {
    "S0": ("Sabit takvim", "fixed", None),
    "MODEL": ("İkiz: yalnız model", "jit", "model"),
    "SENSOR": ("İkiz: yalnız sensör", "jit", "sensor"),
    "ENKF": ("İkiz: model + sensör (EnKF)", "jit", "enkf"),
}


# Karşılaştırma ölçütü (ikiz değil): dünyanın gizli hücre durumunu ve bugünün gerçek havasını bilen,
# zon başına tek doz veren kâhin. Verilen zon düzeninde stressiz sulamanın alt sınırını verir.
BENCHMARKS: Dict[str, tuple] = {"ORACLE": ("Zon kâhini (alt sınır)", "oracle", None)}


class ZoneTwin:
    """Bir sulama zonunun dijital ikizi. Dünyanın hücre parametrelerini bilmez; nominal değerleri kullanır."""

    def __init__(
        self,
        zone: WorldZone,
        spec: dict,
        cfg: TwinConfig,
        policy: str,
        estimator: Optional[str],
        margin: float,
        seed: int,
    ):
        self.zone = zone
        self.policy = policy
        self.estimator = estimator
        self.margin = margin
        self.cfg = cfg
        self.fc = float(spec["soil"]["theta_fc"]["mean"])
        self.wp = float(spec["soil"]["theta_wp"]["mean"])
        self.zr = zone.zr_nominal
        self.p = zone.p_nominal
        self.taw = 1000.0 * (self.fc - self.wp) * self.zr
        self.raw = self.p * self.taw
        self.runoff = float(cfg.soil.runoff_threshold_mm.value)
        self.cap = float(cfg.irrigation.max_gross_dose_mm.value)
        self.dr_hat = 0.0
        self.last_dose = 0.0
        self.enkf = None
        # isteğe bağlı günlük tahmin tablosu (sütunlar: eto_fc, rain_fc); None ise kalıcılık kullanılır
        self.forecast: Optional[pd.DataFrame] = None
        if estimator == "enkf":
            self.enkf = EnsembleKalmanFilter(
                num_members=40,
                theta_fc=self.fc,
                theta_wp=self.wp,
                root_depth_m=self.zr,
                p_depletion=self.p,
                obs_error_std=float(cfg.assimilation.obs_error_std.value),
                proc_error_std_dr=float(cfg.assimilation.proc_error_std_dr.value),
                seed=seed,
            )

    def kc(self, month: int) -> float:
        return float(self.zone.kc_nominal[_stage_index(month)])

    def _model_step(self, dr: float, eto: float, rain: float, month: int, dose: float) -> float:
        ks = 1.0 if dr <= self.raw else max(0.0, (self.taw - dr) / ((1.0 - self.p) * self.taw))
        p_net = rain - max(0.0, rain - self.runoff)
        tmp = dr - p_net - self.zone.efficiency * dose + ks * self.kc(month) * eto
        return float(np.clip(tmp, 0.0, self.taw))

    def _fixed_dose(self, day: int) -> float:
        interval = int(self.cfg.irrigation.s0_interval_days.value)
        return float(self.cfg.irrigation.s0_dose_mm.value) if day % interval == 0 else 0.0

    def _jit_dose(self, dr: float, etc_mm: float, rain_mm: float) -> float:
        """Gün sonu açığı hedefin (margin · RAW) altında tutacak brüt doz; rain_mm beklenen yağış."""
        p_net = rain_mm - max(0.0, rain_mm - self.runoff)
        need = dr + etc_mm - p_net - self.margin * self.raw
        return float(np.clip(need / self.zone.efficiency, 0.0, self.cap)) if need > 0 else 0.0

    def decide(
        self, day: int, date: pd.Timestamp, yesterday: Optional[pd.Series], obs: Optional[float]
    ) -> float:
        """Sabah kararı: dünün havası ve bugünkü sensör okuması → bugünkü brüt sulama önerisi [mm].

        Tahmin kullanılmaz: bugünün ETc'si dünkü gibi, yağış yok varsayılır (kalıcılık).
        """
        if self.policy == "fixed":
            self.last_dose = self._fixed_dose(day)
            return self.last_dose
        eto_y = self.estimate(date, yesterday, obs)
        if self.forecast is not None and date in self.forecast.index:
            row = self.forecast.loc[date]
            etc, rain = self.kc(date.month) * float(row["eto_fc"]), float(row["rain_fc"])
        else:
            etc, rain = self.kc(date.month) * eto_y, 0.0
        self.last_dose = self._jit_dose(self.dr_hat, etc, rain)
        return self.last_dose

    def estimate(self, date: pd.Timestamp, yesterday: Optional[pd.Series], obs: Optional[float]) -> float:
        """Sabah durum kestirimi (dünkü hava + dünkü doz + bugünkü sensör). Dünkü ETo'yu döndürür."""
        if yesterday is not None:
            eto_y, rain_y, month_y = (
                float(yesterday["eto_mm"]),
                float(yesterday["rain_mm"]),
                yesterday.name.month,
            )
        else:
            eto_y, rain_y, month_y = 0.0, 0.0, date.month

        if self.estimator == "model":
            if yesterday is not None:
                self.dr_hat = self._model_step(self.dr_hat, eto_y, rain_y, month_y, self.last_dose)
        elif self.estimator == "sensor":
            if obs is not None:
                self.dr_hat = float(np.clip(1000.0 * self.zr * (self.fc - obs), 0.0, self.taw))
            elif yesterday is not None:
                self.dr_hat = self._model_step(self.dr_hat, eto_y, rain_y, month_y, self.last_dose)
        elif self.estimator == "enkf":
            if yesterday is not None:
                self.enkf.forecast_step(
                    eto_mm=eto_y,
                    kc=self.kc(month_y),
                    precip_mm=rain_y,
                    irrigation_mm=self.last_dose,
                    irr_efficiency=self.zone.efficiency,
                )
            self.dr_hat, _, _ = self.enkf.analysis_step(obs)
        return eto_y

    def plan(self, forecast: pd.DataFrame, first_day: int) -> List[tuple]:
        """Tahmin günleri için (brüt doz, gün sonu tahmini açık) listesi.

        Beklenen yağış = tahmin yağışı × yağış olasılığı (karar kuralı varsayımı). Kestirim bugünkü
        sabah değerinden başlar ve ikizin nominal modeliyle ileri taşınır; gerçekleşme henüz bilinmez.
        """
        x = self.dr_hat
        out = []
        for k, (date, row) in enumerate(forecast.iterrows()):
            rain_exp = float(row["rain_mm"]) * float(row.get("rain_prob_pct", 100.0)) / 100.0
            etc = self.kc(date.month) * float(row["eto_mm"])
            if self.policy == "fixed":
                dose = self._fixed_dose(first_day + k)
            else:
                dose = self._jit_dose(x, etc, rain_exp)
            x = self._model_step(x, float(row["eto_mm"]), rain_exp, date.month, dose)
            out.append((dose, x))
        return out


@dataclass
class WorldRun:
    strategy: str
    dates: pd.DatetimeIndex
    dr_true: np.ndarray  # (T, n) gün başı gerçek tükenme [mm]
    ks: np.ndarray  # (T, n)
    dose_mm: np.ndarray  # (T, Z) zon brüt sulama önerisi
    dr_hat: np.ndarray  # (T, Z) ikizin kestirimi (karar anında)
    dr_zone_true: np.ndarray  # (T, Z) zonun gerçek ortalama tükenmesi (gün başı)
    water_m3: np.ndarray  # (T,)
    dp_m3: np.ndarray  # (T,)
    stressed_area_frac: np.ndarray  # (T,)
    sensors: pd.DataFrame
    source: str
    dr_end: Optional[np.ndarray] = None  # (n,) son günün sonundaki gerçek tükenme
    twins: Optional[list] = None
    qc: Optional[list] = None  # sensör başına OnlineSensorQC (qc=True ise)
    qc_enabled: bool = False


def run_world(
    world: World,
    weather: pd.DataFrame,
    strategy: str,
    margin: float = 0.9,
    sensor_seed: int = 0,
    config: Optional[TwinConfig] = None,
    forecast: Optional[pd.DataFrame] = None,
    qc: bool = False,
    qc_drift: bool = True,
) -> WorldRun:
    """Dünyayı gün gün yürütür. `qc=True` ise her sensör okuması ikize ulaşmadan çevrimiçi kalite kontrolünden
    geçer (twin.qc.online); reddedilen okuma kullanılmaz, zonda geçerli okuma kalmazsa ikiz modelle devam eder.
    `qc_drift=True` iken QC, sensörü görmeyen açık döngü zon modeliyle tutarlılık (kayma) testini de uygular.

    `forecast` verilirse ikizler bugünün kararında tahmin edilen ETo ve
    yağışı (`eto_fc`, `rain_fc`) kullanır; verilmezse dünkü ETo ve sıfır yağış (kalıcılık)."""
    cfg = config or TwinConfig()
    _, policy, estimator = {**STRATEGIES, **BENCHMARKS}[strategy]
    if weather[["eto_mm", "rain_mm"]].isna().any().any():
        raise ValueError(
            "Hava verisinde boş (NaN) ETo/yağış var; dünya durumu bozulur. Önce boşlukları giderin."
        )
    rng = np.random.default_rng(sensor_seed)
    twins = [
        ZoneTwin(z, world.spec, cfg, policy, estimator, margin, seed=sensor_seed * 1000 + i)
        for i, z in enumerate(world.zones)
    ]
    for tw in twins:
        tw.forecast = forecast
    for s in world.sensors:
        s.sensor._frozen = None
    qcs = (
        [OnlineSensorQC(float(world.spec["soil"]["theta_fc"]["mean"]), cfg.sensor_qc) for _ in world.sensors]
        if qc
        else None
    )

    n, nz, t_len = len(world.veg_c), len(world.zones), len(weather)
    taw, raw, p = world.taw_c, world.raw_c, world.p_c
    eff_z = np.array([z.efficiency for z in world.zones])
    area_z = np.array([z.area_m2 for z in world.zones])
    runoff = float(cfg.soil.runoff_threshold_mm.value)
    stage_kc = world.kc_c * world.micro_c[:, None]

    dr = np.zeros(n)
    out_dr = np.empty((t_len, n), dtype=np.float32)
    out_ks = np.empty((t_len, n), dtype=np.float32)
    out_dose = np.zeros((t_len, nz))
    out_hat = np.zeros((t_len, nz))
    out_true = np.zeros((t_len, nz))
    water = np.zeros(t_len)
    dp_m3 = np.zeros(t_len)
    stressed = np.zeros(t_len)
    sensor_rows = []
    counts = np.bincount(world.zone_c, minlength=nz)
    # kayma testi için açık döngü referansı: zon başına nominal model, uygulanan doz + gözlenen hava, sensör görmez
    ol_dr = np.zeros(nz)

    for t in range(t_len):
        date = weather.index[t]
        w = weather.iloc[t]
        theta = world.fc_c - dr / (1000.0 * world.zr_c)
        zone_obs: List[List[float]] = [[] for _ in range(nz)]
        if qcs is not None and t > 0:
            # doygunluk: dünkü net su girdisi ikizin dün sabahki açık kestirimini tamponla aşıyor mu?
            rain_y = float(weather["rain_mm"].iloc[t - 1])
            input_y = rain_y - max(0.0, rain_y - runoff) + eff_z * out_dose[t - 1]
            saturated_z = input_y >= out_hat[t - 1] + float(cfg.sensor_qc.saturation_buffer_mm.value)
        else:
            saturated_z = np.zeros(nz, dtype=bool)
        if t > 0:
            y = weather.iloc[t - 1]
            ol_dr = np.array(
                [
                    tw._model_step(
                        ol_dr[zi], float(y["eto_mm"]), float(y["rain_mm"]), y.name.month, out_dose[t - 1, zi]
                    )
                    for zi, tw in enumerate(twins)
                ]
            )
        theta_ol = np.array([tw.fc - ol_dr[zi] / (1000.0 * tw.zr) for zi, tw in enumerate(twins)])
        for si, s in enumerate(world.sensors):
            r = s.sensor.read(float(theta[s.cell]), t, rng)
            reason = "ok" if not np.isnan(r) else "nodata"
            used = None if np.isnan(r) else r
            if qcs is not None:
                used, reason = qcs[si].update(
                    r,
                    saturated=bool(saturated_z[s.zone_index]),
                    theta_model=float(theta_ol[s.zone_index]) if qc_drift else None,
                )
            if used is not None:
                zone_obs[s.zone_index].append(used)
            sensor_rows.append(
                {
                    "time": date,
                    "sensor_id": s.sensor.sensor_id,
                    "zone": world.zones[s.zone_index].zone_id,
                    "theta_true": float(theta[s.cell]),
                    "theta_read": r,
                    "fault_type": s.sensor.fault.type,
                    "fault_active": s.sensor.is_faulty(t),
                    "qc_reason": reason,
                    "used": used is not None,
                    "theta_openloop": float(theta_ol[s.zone_index]),
                    "drift_slope": qcs[si].drift_slope if qcs is not None else float("nan"),
                }
            )
        yesterday = weather.iloc[t - 1] if t > 0 else None
        for zi, tw in enumerate(twins):
            obs = float(np.mean(zone_obs[zi])) if zone_obs[zi] else None
            out_dose[t, zi] = tw.decide(t, date, yesterday, obs)
            out_hat[t, zi] = tw.dr_hat
        out_true[t] = np.bincount(world.zone_c, weights=dr, minlength=nz) / np.maximum(counts, 1)

        ks = np.where(dr <= raw, 1.0, np.clip((taw - dr) / ((1.0 - p) * taw), 0.0, 1.0))
        eta = ks * stage_kc[:, _stage_index(date.month)] * float(w["eto_mm"])
        rain = float(w["rain_mm"])
        p_net = rain - max(0.0, rain - runoff)
        if policy == "oracle":
            # zondaki her hücrenin gün sonu açığı margin·RAW altında kalsın; doz en zorlu hücreye göre
            need = np.maximum(dr + eta - p_net - margin * raw, 0.0)
            zone_need = np.zeros(nz)
            np.maximum.at(zone_need, world.zone_c, need)
            out_dose[t] = np.clip(zone_need / eff_z, 0.0, twins[0].cap)
            out_hat[t] = out_true[t]
        tmp = dr - p_net - (out_dose[t] * eff_z)[world.zone_c] + eta
        dp = np.maximum(0.0, -tmp)
        out_dr[t], out_ks[t] = dr, ks
        stressed[t] = float(np.mean(ks < 0.999))
        water[t] = float(np.sum(out_dose[t] * area_z) / 1000.0)
        dp_m3[t] = float(dp.sum() * world.cell_area_m2 / 1000.0)
        dr = np.clip(tmp, 0.0, taw)

    return WorldRun(
        strategy=strategy,
        dates=weather.index,
        dr_true=out_dr,
        ks=out_ks,
        dose_mm=out_dose,
        dr_hat=out_hat,
        dr_zone_true=out_true,
        water_m3=water,
        dp_m3=dp_m3,
        stressed_area_frac=stressed,
        sensors=pd.DataFrame(sensor_rows),
        source=weather.attrs.get("source", "unknown"),
        dr_end=dr,
        twins=twins,
        qc=qcs,
        qc_enabled=qc,
    )


def plan_from_forecast(
    world: World,
    weather: pd.DataFrame,
    strategy: str,
    margin: float = 0.9,
    sensor_seed: int = 0,
    config: Optional[TwinConfig] = None,
    qc: bool = False,
) -> tuple:
    """Geçmiş günlerle dünyayı ve ikizi bugüne getirir, bugünden itibaren tahminle sulama planı üretir.

    `weather` içinde `is_forecast` sütunu olmalı (bkz. twin.data.forecast). Dönüş: (geçmiş koşu, plan tablosu).
    """
    past = weather[~weather["is_forecast"]].copy()
    fc = weather[weather["is_forecast"]].copy()
    past.attrs = dict(weather.attrs)
    run = run_world(world, past, strategy, margin=margin, sensor_seed=sensor_seed, config=config, qc=qc)

    # bugün sabah: sanal sensörler dünyanın son durumunu okur, ikiz kestirimini günceller
    rng = np.random.default_rng(sensor_seed + 1)
    theta = world.fc_c - run.dr_end / (1000.0 * world.zr_c)
    first_day = len(past)
    zone_obs: List[List[float]] = [[] for _ in world.zones]
    for si, s in enumerate(world.sensors):
        r = s.sensor.read(float(theta[s.cell]), first_day, rng)
        used = None if np.isnan(r) else r
        if run.qc is not None:
            used, _ = run.qc[si].update(r)
        if used is not None:
            zone_obs[s.zone_index].append(used)
    rows = []
    for zi, (z, tw) in enumerate(zip(world.zones, run.twins)):
        if tw.policy != "fixed":
            tw.estimate(fc.index[0], past.iloc[-1], float(np.mean(zone_obs[zi])) if zone_obs[zi] else None)
        dr_today = tw.dr_hat
        for (date, row), (dose, x_end) in zip(fc.iterrows(), tw.plan(fc, first_day)):
            rows.append(
                {
                    "time": date,
                    "zone": z.zone_id,
                    "label": z.label,
                    "system": z.irrigation,
                    "dose_mm": dose,
                    "minutes": dose / z.application_rate_mm_h * 60.0,
                    "water_m3": dose * z.area_m2 / 1000.0,
                    "deficit_ratio_end": x_end / tw.raw,
                    "deficit_ratio_today": dr_today / tw.raw,
                    "eto_mm": float(row["eto_mm"]),
                    "rain_mm": float(row["rain_mm"]),
                    "rain_prob_pct": float(row.get("rain_prob_pct", np.nan)),
                }
            )
    return run, pd.DataFrame(rows)


def runtime_minutes(world: World, dose_mm: np.ndarray) -> np.ndarray:
    """Zon brüt dozlarını [mm] sulama sisteminin çalışma süresine [dk] çevirir: süre = doz / uygulama hızı."""
    rate = np.array([z.application_rate_mm_h for z in world.zones])
    return dose_mm / rate * 60.0


def summarize_run(run: WorldRun) -> Dict[str, float]:
    err = run.dr_hat - run.dr_zone_true
    if {**STRATEGIES, **BENCHMARKS}[run.strategy][2] is None:  # sabit takvim ve kâhin kestirim yapmaz
        err = np.full_like(err, np.nan)
    return {
        "su_m3": float(run.water_m3.sum()),
        "stresli_alan_ort_pct": 100.0 * float(run.stressed_area_frac.mean()),
        "stresli_alan_maks_pct": 100.0 * float(run.stressed_area_frac.max()),
        "derin_sizma_m3": float(run.dp_m3.sum()),
        "kestirim_rmse_mm": float(np.sqrt(np.mean(err**2))),
        "kestirim_yanlilik_mm": float(np.mean(err)),
    }
