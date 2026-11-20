"""Sanal Park Test Alanı (Streamlit).

Çalıştırma:  .venv/bin/streamlit run src/twin/ui/sanal_park.py

Gerçek Yıldız Korusu sınırı içinde rastgele üretilmiş heterojen bir sanal park (çim, ağaçlık, çalı, çiçek tarhı),
haritaya serpiştirilmiş sanal sensörler ve bunları okuyan dijital ikiz. İkiz yalnız sensörleri ve dünün havasını
görür; sanal dünyanın gerçek toprak durumu ondan gizlidir. Üretilen sulama miktarları yalnızca ÖNERİDİR; hiçbir
aktüatöre veya MQTT konusuna komut gönderilmez.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from twin.config import TwinConfig
from twin.data.forecast import fetch_open_meteo_daily
from twin.qc.online import QC_REASONS
from twin.sim.engine import prepare_season_weather
from twin.sim.virtual_world import (
    STRATEGIES,
    VEG_KEYS,
    build_world,
    load_world_spec,
    plan_from_forecast,
    run_world,
    runtime_minutes,
    summarize_run,
)

ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = ROOT / "data" / "scenarios" / "yildiz_dunya.json"
GEOJSON = ROOT / "data" / "public" / "parks.geojson"

VEG_COLORS = {"turf": "#7bc96f", "tree": "#1b6e3a", "shrub": "#c9a227", "flower": "#d6457a"}
SYSTEM_COLORS = {"yağmurlama": ("#3d8bd9", "#22609f"), "damla": ("#2fa58c", "#1d7462")}
STRAT_COLORS = {"S0": "#9a6700", "MODEL": "#6e7781", "SENSOR": "#8250df", "ENKF": "#0969da"}
FAULT_TEXT = {"none": "sağlam", "drift": "kayıyor", "freeze": "donuyor", "dropout": "veri kaybediyor"}
FAULT_COLOR = {"none": "#ffffff", "drift": "#f0b400", "freeze": "#f0b400", "dropout": "#cf222e"}
# Dr/RAW: 0 = toprak dolu, 1 = stres eşiği, ≥ 2 = ağır stres
STRESS_SCALE = [[0.0, "#2c7fb8"], [0.35, "#a6d9c7"], [0.5, "#f6f2a4"], [0.75, "#f08a4b"], [1.0, "#b2182b"]]

CSS = """
<style>
.block-container {padding-top: 2.2rem; max-width: 1300px;}
.layer {border:1px solid rgba(128,128,128,.25); border-radius:10px; padding:.8rem 1rem; height:100%;}
.layer b {display:block; margin-bottom:.25rem;}
.layer span {opacity:.8; font-size:.9rem;}
.tag {display:inline-block; padding:.1rem .5rem; border-radius:999px; font-size:.8rem;
      border:1px solid rgba(128,128,128,.35); margin:0 .35rem .35rem 0;}
.lead {font-size:1.05rem; opacity:.85; margin-top:-.4rem;}
</style>
"""


# toprak nemi durumu: açık/eşik oranına göre dört sınıf (eşikler: 0,5 · güvenlik payı · 1,0)
STATE_LABELS = ["Nemli", "Uygun", "Sulama gerekli", "Stres (susuz)"]
STATE_COLORS = ["#2c7fb8", "#8fd19e", "#f2c14e", "#c0392b"]
VEG_SHORT = {"turf": "Çim", "tree": "Ağaç", "shrub": "Çalı", "flower": "Çiçek"}


def state_class(ratio, margin: float):
    r = np.asarray(ratio, dtype=float)
    out = np.select([r < 0.5, r < margin, r < 1.0], [0, 1, 2], default=3).astype(float)
    return np.where(np.isnan(r), np.nan, out)


def _discrete_scale(colors):
    n = len(colors)
    scale = []
    for i, c in enumerate(colors):
        scale += [[i / n, c], [(i + 1) / n, c]]
    return scale


def zone_name(z) -> str:
    return f"{VEG_SHORT.get(z.veg, z.veg)} {z.zone_id.split('-')[-1]}"


def nominal_raw(world) -> np.ndarray:
    soil = world.spec["soil"]
    taw = np.array(
        [1000 * (soil["theta_fc"]["mean"] - soil["theta_wp"]["mean"]) * z.zr_nominal for z in world.zones]
    )
    return np.array([z.p_nominal for z in world.zones]) * taw


def zone_borders(world):
    """Komşu hücrelerin zonu farklıysa aradaki kenarı çizgi parçası olarak döndürür."""
    grid = world.to_grid(world.zone_c.astype(float))
    grid = np.where(np.isnan(grid), -1, grid)
    g = float(world.spec["grid_m"]) / 2
    xs, ys = [], []
    r, c = np.nonzero((grid[:, :-1] != grid[:, 1:]) & (grid[:, :-1] >= 0) & (grid[:, 1:] >= 0))
    for ri, ci in zip(r, c):
        xb = world.x[ci] + g
        xs += [xb, xb, None]
        ys += [world.y[ri] - g, world.y[ri] + g, None]
    r, c = np.nonzero((grid[:-1, :] != grid[1:, :]) & (grid[:-1, :] >= 0) & (grid[1:, :] >= 0))
    for ri, ci in zip(r, c):
        yb = world.y[ri] + g
        xs += [world.x[ci] - g, world.x[ci] + g, None]
        ys += [yb, yb, None]
    return xs, ys


def state_map(world, cell_ratio, margin: float, zone_text, selected=None, height=560):
    """Dört sınıflı toprak nemi haritası; zon sınırları, büyük zonlarda ad etiketi, tıklanabilir hücreler."""
    cls = state_class(cell_ratio, margin)
    fig = go.Figure()
    fig.add_trace(
        go.Heatmap(
            x=world.x,
            y=world.y,
            z=world.to_grid(cls),
            zmin=-0.5,
            zmax=3.5,
            colorscale=_discrete_scale(STATE_COLORS),
            showscale=False,
            hoverinfo="skip",
        )
    )
    if selected is not None:
        sel = world.to_grid(np.where(world.zone_c == selected, 1.0, np.nan))
        fig.add_trace(
            go.Heatmap(
                x=world.x,
                y=world.y,
                z=sel,
                colorscale=[[0, "#000"], [1, "#000"]],
                opacity=0.25,
                showscale=False,
                hoverinfo="skip",
            )
        )
    bx, by = zone_borders(world)
    fig.add_trace(
        go.Scatter(
            x=bx,
            y=by,
            mode="lines",
            line=dict(color="rgba(36,41,47,.55)", width=1),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    add_boundary(fig, world)
    # tıklama katmanı: her hücre bir nokta (görünmez); customdata = zon dizini
    xs = world.x[world.cell_rc[:, 1]]
    ys = world.y[world.cell_rc[:, 0]]
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="markers",
            marker=dict(size=9, color="rgba(0,0,0,0.01)", symbol="square"),
            customdata=world.zone_c,
            hovertext=[zone_text[zi] for zi in world.zone_c],
            hoverinfo="text",
            showlegend=False,
            name="zonlar",
        )
    )
    big = [zi for zi, z in enumerate(world.zones) if z.area_m2 >= 6000]
    lx, ly, lt = [], [], []
    for zi in big:
        cells = world.cell_rc[world.zone_c == zi]
        # etiketi zonun merkezine en yakın iç hücreye koy (zon dışına taşmasın)
        cx, cy = world.x[cells[:, 1]].mean(), world.y[cells[:, 0]].mean()
        k = np.argmin((world.x[cells[:, 1]] - cx) ** 2 + (world.y[cells[:, 0]] - cy) ** 2)
        lx.append(world.x[cells[k, 1]])
        ly.append(world.y[cells[k, 0]])
        lt.append(f"<b>{zone_name(world.zones[zi])}</b>")
    fig.add_trace(
        go.Scatter(
            x=lx,
            y=ly,
            mode="text",
            text=lt,
            textfont=dict(size=11, color="#111"),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    for lab, col in zip(STATE_LABELS, STATE_COLORS):
        fig.add_trace(
            go.Scatter(
                x=[None], y=[None], mode="markers", marker=dict(size=13, color=col, symbol="square"), name=lab
            )
        )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, scaleanchor="x", constrain="domain")
    fig.update_layout(
        height=height,
        margin=dict(l=0, r=0, t=0, b=0),
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=1.02, x=0, yanchor="bottom"),
        clickmode="event+select",
        dragmode=False,
        hoverlabel=dict(bgcolor="white"),
    )
    return fig


def pick_zone(event, key: str, n_zones: int, default: int) -> int:
    """Haritadan tıklanan zonu oturumda tutar."""
    pts = (event or {}).get("selection", {}).get("points", []) if event else []
    for pt in pts:
        cd = pt.get("customdata")
        if cd is not None:
            st.session_state[key] = int(cd[0] if isinstance(cd, (list, tuple)) else cd)
            break
    return int(st.session_state.get(key, default)) % max(n_zones, 1)


def zone_card(world, zi: int, run, weather, t_now: int, dr_hat_now: float, margin: float, plan=None):
    """Seçili zonun ayrıntısı: bitki, sistem, toprak nemi, son sulama, son yağış, sensörler, kısa geçmiş."""
    qc_active = bool(getattr(run, "qc_enabled", False))
    z = world.zones[zi]
    soil = world.spec["soil"]
    fc, wp = soil["theta_fc"]["mean"], soil["theta_wp"]["mean"]
    taw = 1000 * (fc - wp) * z.zr_nominal
    raw = z.p_nominal * taw
    ratio = dr_hat_now / raw
    cls = int(state_class(ratio, margin))
    theta = fc - dr_hat_now / (1000 * z.zr_nominal)
    left = max(0.0, 1 - dr_hat_now / taw)
    dates = run.dates
    st.markdown(
        f"### {zone_name(z)} · {world.spec['vegetation'][z.veg]['label']}"
        f"<br><span style='color:{STATE_COLORS[cls]}; font-weight:600'>● {STATE_LABELS[cls]}</span>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"{z.area_m2 / 10000:.2f} ha · {z.irrigation}, {z.application_rate_mm_h:g} mm/saat · "
        f"kök derinliği ≈ {z.zr_nominal:.2f} m · Kc (yaz) {z.kc_nominal[1]:.2f} · {z.n_cells} hücre"
    )
    a, b = st.columns(2)
    a.metric(
        "Toprak nemi (ikiz)",
        f"{theta:.3f} m³/m³",
        help=f"İkizin kestirimi; tarla kapasitesi {fc:.2f}, solma noktası {wp:.2f} (nominal).",
    )
    b.metric(
        "Kullanılabilir su",
        f"%{100 * left:.0f}",
        help=f"Kök bölgesinde {taw:.0f} mm kullanılabilir su var; stres eşiği {raw:.0f} mm açık.",
    )

    past_dose = run.dose_mm[:t_now, zi]
    irr = np.flatnonzero(past_dose > 0.05)
    if irr.size:
        i = irr[-1]
        last_irr = (
            f"{dates[i]:%d %b} · {past_dose[i]:.1f} mm ({past_dose[i] / z.application_rate_mm_h * 60:.0f} dk)"
        )
    else:
        last_irr = f"son {t_now} günde sulanmadı"
    rain = weather["rain_mm"].to_numpy()[:t_now]
    wet = np.flatnonzero(rain >= 1.0)
    last_rain = f"{dates[wet[-1]]:%d %b} · {rain[wet[-1]]:.1f} mm" if wet.size else f"son {t_now} günde yok"
    rain7 = float(rain[-7:].sum()) if t_now else 0.0
    st.markdown(
        f"- **Son sulama:** {last_irr}\n"
        f"- **Son yağış (≥ 1 mm):** {last_rain} · son 7 gün toplam {rain7:.1f} mm\n"
        f"- **Son 30 günde verilen su:** {past_dose[-30:].sum():.0f} mm · "
        f"{past_dose[-30:].sum() * z.area_m2 / 1000:,.0f} m³"
    )
    st.caption(
        f"Simülasyon {dates[0]:%d %b %Y} tarihinde toprak tarla kapasitesinde (dolu) başlar (varsayım); "
        "ilk haftaların sulama geçmişi bu başlangıca bağlıdır."
    )
    if plan is not None:
        zp = plan[plan["zone"] == z.zone_id]
        today = zp.iloc[0]
        st.markdown(
            f"**Bugünkü öneri:** {today['minutes']:.0f} dk ({today['dose_mm']:.1f} mm, {today['water_m3']:,.0f} m³) · "
            f"7 gün: {zp['minutes'].sum():.0f} dk, {zp['water_m3'].sum():,.0f} m³"
        )

    # sensörler (son okuma)
    sids = [s for s in world.sensors if s.zone_index == zi]
    if sids and t_now > 0:
        last = run.sensors[run.sensors["time"] == dates[t_now - 1]].set_index("sensor_id")
        rows = []
        for s in sids:
            r = last.loc[s.sensor.sensor_id] if s.sensor.sensor_id in last.index else None
            rows.append(
                {
                    "sensör": s.sensor.sensor_id,
                    f"okuma {dates[t_now - 1]:%d %b}": "veri yok"
                    if r is None or np.isnan(r["theta_read"])
                    else f"{r['theta_read']:.3f}",
                    "QC kararı": "kapalı"
                    if r is None or "qc_reason" not in r or not qc_active
                    else QC_REASONS.get(r["qc_reason"], r["qc_reason"]),
                    "gerçek arıza (ikiz bilmez)": FAULT_TEXT.get(s.sensor.fault.type, s.sensor.fault.type),
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    # kısa geçmiş: kullanılabilir su (ikiz) + sulama ve yağış
    lo = max(0, t_now - 30)
    hist_d = dates[lo:t_now]
    fz = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.6, 0.4], vertical_spacing=0.06)
    if t_now > lo:
        fz.add_trace(
            go.Scatter(
                x=hist_d,
                y=100 * (1 - run.dr_hat[lo:t_now, zi] / taw),
                name="kullanılabilir su (ikiz)",
                line=dict(color="#0969da", width=2.5),
            ),
            row=1,
            col=1,
        )
        fz.add_trace(
            go.Scatter(
                x=hist_d,
                y=100 * (1 - run.dr_zone_true[lo:t_now, zi] / taw),
                name="sanal gerçek (zon ort., ikiz görmez)",
                line=dict(color="#6e7781", width=1.5, dash="dot"),
            ),
            row=1,
            col=1,
        )
        fz.add_trace(
            go.Bar(x=hist_d, y=run.dose_mm[lo:t_now, zi], name="sulama (mm)", marker_color="#2fa58c"),
            row=2,
            col=1,
        )
        fz.add_trace(
            go.Bar(x=hist_d, y=weather["rain_mm"].iloc[lo:t_now], name="yağış (mm)", marker_color="#9aa4ae"),
            row=2,
            col=1,
        )
    fz.add_hline(
        y=100 * (1 - raw / taw),
        line_dash="dash",
        line_color=STATE_COLORS[3],
        row=1,
        col=1,
        annotation_text="stres eşiği",
        annotation_position="bottom left",
    )
    fz.update_yaxes(title_text="%", range=[0, 105], row=1, col=1)
    fz.update_yaxes(title_text="mm", row=2, col=1)
    fz.update_layout(
        height=330,
        margin=dict(l=0, r=0, t=10, b=0),
        barmode="group",
        legend=dict(orientation="h", y=-0.15),
        hovermode="x unified",
    )
    st.plotly_chart(fz, width="stretch", key=f"zone_hist_{zi}_{t_now}")


def weather_chart(recent: pd.DataFrame, today) -> go.Figure:
    """Üstte yağış, altta ETo; gerçekleşen (gri) ve tahmin (mavi/turuncu) ayrı renk, tahmin alanı gölgeli."""
    past = recent[~recent["is_forecast"]]
    fc = recent[recent["is_forecast"]]
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.55, 0.45],
        subplot_titles=("Yağış (mm/gün)", "Buharlaşma ihtiyacı ETo (mm/gün)"),
    )
    fig.add_trace(
        go.Bar(
            x=past.index,
            y=past["rain_mm"],
            name="son günler (model analizi)",
            marker_color="#9aa4ae",
            hovertemplate="%{x|%d %b}: %{y:.1f} mm<extra>geçmiş</extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=fc.index,
            y=fc["rain_mm"],
            name="tahmin",
            marker_color="#0969da",
            text=[
                f"{r:.1f} mm<br>%{p:.0f}" if r >= 0.1 else ""
                for r, p in zip(fc["rain_mm"], fc["rain_prob_pct"])
            ],
            textposition="outside",
            textfont=dict(size=12),
            cliponaxis=False,
            hovertemplate="%{x|%d %b}: %{y:.1f} mm, olasılık %{customdata:.0f}%<extra>tahmin</extra>",
            customdata=fc["rain_prob_pct"],
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=past.index,
            y=past["eto_mm"],
            name="ETo geçmiş",
            mode="lines+markers",
            line=dict(color="#9aa4ae", width=2),
            showlegend=False,
            hovertemplate="%{x|%d %b}: %{y:.1f} mm<extra>geçmiş</extra>",
        ),
        row=2,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=fc.index,
            y=fc["eto_mm"],
            name="ETo tahmin",
            mode="lines+markers",
            line=dict(color="#cf6a00", width=2.5),
            showlegend=False,
            hovertemplate="%{x|%d %b}: %{y:.1f} mm<extra>tahmin</extra>",
        ),
        row=2,
        col=1,
    )
    x0 = pd.Timestamp(today) - pd.Timedelta(hours=12)
    x1 = recent.index.max() + pd.Timedelta(hours=12)
    for r in (1, 2):
        fig.add_vrect(
            x0=x0,
            x1=x1,
            fillcolor="#0969da",
            opacity=0.07,
            line_width=0,
            row=r,
            col=1,
            annotation_text="<b>TAHMİN</b>" if r == 1 else None,
            annotation_position="top left",
            annotation_font=dict(color="#0969da", size=12),
        )
    ymax = max(1.0, float(recent["rain_mm"].max()) * 1.35)
    fig.update_yaxes(range=[0, ymax], row=1, col=1)
    fig.update_yaxes(range=[0, max(1.0, float(recent["eto_mm"].max()) * 1.2)], row=2, col=1)
    fig.update_xaxes(dtick=86400000 * 2, tickformat="%d %b", row=2, col=1)
    fig.update_layout(
        height=420,
        margin=dict(l=0, r=0, t=40, b=0),
        bargap=0.3,
        legend=dict(orientation="h", y=1.12, x=1, xanchor="right"),
        hovermode="x unified",
    )
    return fig


@st.cache_resource(show_spinner="Sanal park üretiliyor…")
def get_world(world_seed: int):
    spec = load_world_spec(SPEC_PATH)
    spec["world_seed"] = world_seed
    return build_world(spec, GEOJSON)


@st.cache_data(show_spinner="Sezon simüle ediliyor…")
def get_runs(world_seed: int, year: int, margin: float, sensor_seed: int, qc: bool = True):
    world = get_world(world_seed)
    weather = prepare_season_weather(season_year=year, source="auto", park_id=world.spec["park_id"])
    runs = {
        k: run_world(world, weather, k, margin=margin, sensor_seed=sensor_seed, qc=qc) for k in STRATEGIES
    }
    for r in runs.values():
        r.twins, r.qc = None, None  # önbelleğe alınmaz
    return runs, weather


@st.cache_data(ttl=3600, show_spinner="Hava tahmini alınıyor (Open-Meteo)…")
def get_forecast(day_key: str):
    era5 = TwinConfig().era5
    return fetch_open_meteo_daily(float(era5.yildiz_lat.value), float(era5.yildiz_lon.value))


@st.cache_data(ttl=3600, show_spinner="İkiz bugüne getiriliyor ve plan yapılıyor…")
def get_plans(world_seed: int, day_key: str, margin: float, sensor_seed: int, qc: bool = True):
    world = get_world(world_seed)
    wx = get_forecast(day_key)
    out, runs = {}, {}
    for k in STRATEGIES:
        run, plan = plan_from_forecast(world, wx, k, margin=margin, sensor_seed=sensor_seed, qc=qc)
        run.twins, run.qc = None, None  # önbelleğe alınmaz
        out[k], runs[k] = plan, run
    return out, wx, runs


def render_forecast(world, shown: str, margin: float, sensor_seed: int, world_seed: int, qc: bool = True):
    """Bugün ve önümüzdeki 7 gün: tahmine dayalı sulama planı."""
    day_key = pd.Timestamp.now(tz="Europe/Istanbul").strftime("%Y-%m-%d")
    try:
        plans, wx, past_runs = get_plans(world_seed, day_key, margin, sensor_seed, qc)
    except Exception as e:  # ağ hatası vb.
        st.error(f"Hava tahmini alınamadı: {e}")
        st.stop()
    plan = plans[shown]
    fc_days = sorted(plan["time"].unique())
    today = fc_days[0]

    st.title("Sulama planı: bugün ve önümüzdeki 7 gün")
    st.markdown(
        '<p class="lead">Son günlerin gerçekleşen havasıyla sanal park bugüne getirilir; ikiz sanal sensörlerden bugünkü '
        "toprak nemini kestirir ve hava tahminine göre her zonun sulama sistemini kaç dakika çalıştıracağını planlar.</p>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<span class="tag">Tahmin: Open-Meteo (bugün + 6 gün)</span>'
        f'<span class="tag">Geçmiş {int((~wx["is_forecast"]).sum())} gün: Open-Meteo model analizi</span>'
        f'<span class="tag">Model ızgara noktası: {wx.attrs.get("grid_latitude")}, {wx.attrs.get("grid_longitude")}</span>'
        '<span class="tag">Park: sanal dünya</span>',
        unsafe_allow_html=True,
    )
    if pd.Timestamp(today).month not in range(4, 11):
        st.info(
            "Şu an sulama dönemi (Nisan–Ekim) dışındayız. Plan yine hesaplanır; kış aylarında bitki katsayısı için "
            "sezon sonu değerleri kullanılır (varsayım)."
        )

    # hava: son 14 gün + tahmin
    st.subheader("Hava: son 14 gün ve önümüzdeki 7 gün")
    recent = wx[wx.index >= pd.Timestamp(today) - pd.Timedelta(days=14)]
    st.plotly_chart(weather_chart(recent, today), width="stretch")
    st.caption(
        "Gri: geçmiş günler (Open-Meteo model analizi; istasyon ölçümü değildir). Mavi/turuncu: bugünden itibaren "
        "tahmin; çubuk üstünde yağış miktarı ve olasılığı. İkiz yağışı miktar × olasılık kadar hesaba katar."
    )

    # stratejilerin 7 günlük toplamları
    st.subheader("Önümüzdeki 7 günde verilecek su")
    cols = st.columns(len(STRATEGIES))
    for col, k in zip(cols, STRATEGIES):
        col.markdown(
            f'<div style="border-left:4px solid {STRAT_COLORS[k]}; padding-left:.6rem"><b>{STRATEGIES[k][0]}</b></div>',
            unsafe_allow_html=True,
        )
        col.metric("7 gün", f"{plans[k]['water_m3'].sum():,.0f} m³")
        col.metric("Bugün", f"{plans[k].loc[plans[k]['time'] == today, 'water_m3'].sum():,.0f} m³")
    st.caption(
        "İkizler tahmin edilen ETo'yu ve beklenen yağışı (miktar × olasılık) hesaba katar; sabit takvim tahmine bakmaz. "
        "Plan her gün yeni tahminle yeniden hesaplanır."
    )

    # bugünkü durum haritası + tıklanınca zon ayrıntısı
    st.subheader(f"Bugünkü toprak nemi ve karar · {STRATEGIES[shown][0]}")
    st.caption("Haritada bir zona tıklayın: sağda bitkisi, toprak nemi, son sulama ve son yağış görünür.")
    today_rows = plan[plan["time"] == today].set_index("zone")
    ratio = np.array([today_rows.loc[z.zone_id, "deficit_ratio_today"] for z in world.zones])
    zone_text = [
        f"<b>{zone_name(z)}</b> · {z.label}<br>{STATE_LABELS[int(state_class(ratio[zi], margin))]}"
        f" (açık/eşik {ratio[zi]:.2f})<br>bugün: {today_rows.loc[z.zone_id, 'minutes']:.0f} dk {z.irrigation}"
        for zi, z in enumerate(world.zones)
    ]
    key = "zone_fc"
    default = int(np.argmax(ratio))
    sel = int(st.session_state.get(key, default)) % len(world.zones)
    c_map, c_card = st.columns([3, 2], gap="medium")
    with c_map:
        ev = st.plotly_chart(
            state_map(world, ratio[world.zone_c], margin, zone_text, selected=sel),
            width="stretch",
            on_select="rerun",
            selection_mode="points",
            key="map_fc",
        )
        new = pick_zone(ev, key, len(world.zones), default)
        if new != sel:
            st.rerun()
    with c_card:
        run_p = past_runs[shown]
        t_now = len(run_p.dates)
        zone_card(
            world,
            sel,
            run_p,
            wx[~wx["is_forecast"]],
            t_now,
            ratio[sel] * nominal_raw(world)[sel],
            margin,
            plan,
        )
    st.caption(
        "Renk ikizin zon başına kestirimidir (bugün sabah, sanal sensörler + son günlerin havası). Nemli: açık eşiğin "
        f"yarısından az · Uygun: güvenlik payının ({margin:.2f}) altında · Sulama gerekli: pay ile eşik arası · "
        "Stres: eşik aşıldı. Çizgiler zon sınırlarıdır."
    )

    # zon × gün planı
    st.subheader("7 günlük plan: zon başına çalışma süresi (dakika)")
    pv = plan.pivot_table(index=["zone", "label", "system"], columns="time", values="minutes").round(0)
    pv.columns = [pd.Timestamp(c).strftime("%a %d %b") for c in pv.columns]
    st.dataframe(
        pv.reset_index().rename(columns={"zone": "zon", "label": "bitki", "system": "sistem"}),
        width="stretch",
        hide_index=True,
    )
    st.caption(
        "Sanal parkta plan sistemlere uygulanır; gerçek parkta karar mekanizması yalnız öneri üretir ve onay gerektirir "
        "(CLAUDE.md §2.3). Geçmiş sezonlarda bu kuralların ne kadar iyi karar verdiğini kenar çubuğundaki "
        "'Geçmiş sezon testi' modunda görebilirsiniz."
    )


def add_boundary(fig, world, row=None, col=None):
    for ring in world.boundary_xy:
        fig.add_trace(
            go.Scatter(
                x=ring[:, 0],
                y=ring[:, 1],
                mode="lines",
                line=dict(color="#24292f", width=1.5),
                hoverinfo="skip",
                showlegend=False,
            ),
            row=row,
            col=col,
        )


def add_sensors(fig, world, day_rows: pd.DataFrame | None, row=None, col=None, show_legend=False):
    for s in world.sensors:
        f = s.sensor.fault.type
        txt = f"{s.sensor.sensor_id}<br>{FAULT_TEXT.get(f, f)}"
        if day_rows is not None:
            r = day_rows[day_rows["sensor_id"] == s.sensor.sensor_id]
            if not r.empty:
                rr = r.iloc[0]
                read = "veri yok" if np.isnan(rr.theta_read) else f"{rr.theta_read:.3f}"
                txt += f"<br>okuma {read} · gerçek {rr.theta_true:.3f} m³/m³"
        fig.add_trace(
            go.Scatter(
                x=[s.sensor.pos[0]],
                y=[s.sensor.pos[1]],
                mode="markers",
                marker=dict(
                    size=10,
                    symbol="diamond",
                    color=FAULT_COLOR.get(f, "#fff"),
                    line=dict(color="#24292f", width=1.5),
                ),
                hovertext=[txt],
                hoverinfo="text",
                showlegend=False,
            ),
            row=row,
            col=col,
        )


st.set_page_config(page_title="Sanal Park · Sulama Dijital İkizi", page_icon="🌳", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

with st.sidebar:
    st.subheader("Mod")
    mode = st.radio(
        "Mod",
        ["Bugün ve 7 gün (tahmin)", "Geçmiş sezon testi (ERA5)"],
        label_visibility="collapsed",
        help="Tahmin modu: bugünden ileriye sulama planı. Test modu: kuralların geçmiş sezonlarda nasıl karar verdiği.",
    )
    st.subheader("Simülasyon")
    year = 2024
    if mode.startswith("Geçmiş"):
        year = st.selectbox("Sulama dönemi (1 Nisan – 31 Ekim)", [2020, 2021, 2022, 2023, 2024], index=4)
    shown = st.selectbox(
        "Haritada gösterilen yönetim", list(STRATEGIES), index=3, format_func=lambda k: STRATEGIES[k][0]
    )
    margin = st.slider(
        "İkizin güvenlik payı (hedef / stres eşiği)",
        0.5,
        1.0,
        0.9,
        0.05,
        help="İkiz, kestirdiği su açığını stres eşiğinin bu oranında tutmaya çalışır. Küçük değer = daha ıslak, daha güvenli.",
    )
    qc_on = st.toggle(
        "Sensör kalite kontrolü (QC)",
        value=True,
        help="Açıkken ikiz her okumayı kullanmadan önce denetler: fiziksel aralık, 3 günden uzun kesinti, eksik oranı, "
        "donmuş değer (SIMPaCT) ve tarla kapasitesi üstü okuma. Reddedilen okuma kullanılmaz; zonda geçerli sensör "
        "kalmazsa ikiz su dengesi modeliyle devam eder.",
    )
    with st.expander("Rastgelelik"):
        world_seed = int(st.number_input("Sanal park tohumu (bitki/toprak dağılımı)", 0, 9999, 7))
        sensor_seed = int(st.number_input("Sensör gürültüsü tohumu", 0, 9999, 0))
    st.caption("Tohumu değiştirmek yeni bir rastgele park ya da yeni sensör gürültüsü üretir.")

world = get_world(world_seed)
if mode.startswith("Bugün"):
    render_forecast(world, shown, margin, sensor_seed, world_seed, qc_on)
    st.stop()
runs, weather = get_runs(world_seed, year, margin, sensor_seed, qc_on)
run = runs[shown]
source = run.source

# ------------------------------------------------------------------ başlık
st.title("Sanal Park Test Alanı")
st.markdown(
    '<p class="lead">Fiziksel kurulumdan önce: rastgele üretilmiş bir park, haritaya dağıtılmış sanal sensörler '
    "ve bu sensörlerle karar veren dijital ikiz. İkiz parkın gerçek durumunu görmez; yalnız sensörleri okur.</p>",
    unsafe_allow_html=True,
)
src_tag = "Hava: ERA5-Land (gerçek)" if source == "era5" else "Hava: SENTETİK"
st.markdown(
    f'<span class="tag">{src_tag}</span><span class="tag">Sınır: İBB Yıldız Korusu poligonu</span>'
    f'<span class="tag">İç dağılım: rastgele sanal dünya</span><span class="tag">Karar: zon sulama sistemleri (sanal)</span>',
    unsafe_allow_html=True,
)
with st.expander("Bu test ortamı nasıl çalışır?"):
    c1, c2, c3 = st.columns(3)
    c1.markdown(
        '<div class="layer"><b>1 · Sanal dünya (gizli)</b><span>Park 10 m\'lik hücrelere bölünür. Her hücrenin bitkisi, '
        "toprağı, kök derinliği ve gölgesi rastgele farklıdır. ERA5 havası ve sulamayla her hücrenin toprak nemi gün gün değişir."
        "</span></div>",
        unsafe_allow_html=True,
    )
    c2.markdown(
        '<div class="layer"><b>2 · Sanal sensörler</b><span>Haritadaki ◆ noktalar yalnız bulundukları hücrenin nemini '
        "ölçer; rastgele gürültü eklenir, bazıları kayar, donar ya da veri kaybeder.</span></div>",
        unsafe_allow_html=True,
    )
    c3.markdown(
        '<div class="layer"><b>3 · Dijital ikiz (sınanan)</b><span>Her sulama zonu için yalnız sensörleri, dünün havasını '
        "ve ortalama (nominal) parametreleri bilir; zonun toprak nemini kestirir ve zonun sulama sistemini "
        "(yağmurlama ya da damla) bugün kaç dakika çalıştıracağına karar verir. Sanal parkta karar sisteme uygulanır, "
        "sonuç dünyadan ölçülür.</span></div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Karşılaştırılan yönetimler: Sabit takvim (3 günde bir 12 mm, sensör ve hava kullanmaz) · İkiz: yalnız model "
        "(sensörsüz su dengesi) · İkiz: yalnız sensör · İkiz: model + sensör (Kalman filtresi). İkiz yönetimleri "
        "tahmini açığı stres eşiğinin altında tutacak kadar sular."
    )

# ------------------------------------------------------------------ sanal park haritası
st.subheader("Sanal park")
map_mode = st.radio(
    "Harita", ["Bitki türleri", "Sulama sistemleri ve zonlar"], horizontal=True, label_visibility="collapsed"
)
veg_grid = world.to_grid(world.veg_c.astype(float))
counts = {k: int((world.veg_c == i).sum()) for i, k in enumerate(VEG_KEYS)}
spec_veg = world.spec["vegetation"]
fig = go.Figure()
for i, k in enumerate(VEG_KEYS if map_mode == "Bitki türleri" else []):
    z = np.where(veg_grid == i, 1.0, np.nan)
    fig.add_trace(
        go.Heatmap(
            x=world.x,
            y=world.y,
            z=z,
            colorscale=[[0, VEG_COLORS[k]], [1, VEG_COLORS[k]]],
            showscale=False,
            name=spec_veg[k]["label"],
            hovertemplate=spec_veg[k]["label"] + "<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            marker=dict(size=12, color=VEG_COLORS[k], symbol="square"),
            name=f"{spec_veg[k]['label']} · {counts[k] * world.cell_area_m2 / 10000:.1f} ha",
        )
    )
if map_mode != "Bitki türleri":
    zone_grid = world.to_grid(world.zone_c.astype(float))
    for zi, zn in enumerate(world.zones):
        color = SYSTEM_COLORS[zn.irrigation][zi % 2]
        fig.add_trace(
            go.Heatmap(
                x=world.x,
                y=world.y,
                z=np.where(zone_grid == zi, 1.0, np.nan),
                colorscale=[[0, color], [1, color]],
                showscale=False,
                hovertemplate=(
                    f"{zn.zone_id} · {zn.label}<br>{zn.irrigation}, {zn.application_rate_mm_h:g} mm/saat"
                    f"<br>{zn.area_m2 / 10000:.2f} ha<extra></extra>"
                ),
            )
        )
        cells = world.cell_rc[world.zone_c == zi]
        cx, cy = world.x[cells[:, 1]].mean(), world.y[cells[:, 0]].mean()
        fig.add_trace(
            go.Scatter(
                x=[cx],
                y=[cy],
                mode="text",
                text=[zn.zone_id],
                textfont=dict(color="#ffffff", size=11),
                hoverinfo="skip",
                showlegend=False,
            )
        )
    for system, (c1_, _) in SYSTEM_COLORS.items():
        rate = next(z.application_rate_mm_h for z in world.zones if z.irrigation == system)
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="markers",
                marker=dict(size=12, color=c1_, symbol="square"),
                name=f"{system} ({rate:g} mm/saat)",
            )
        )
add_boundary(fig, world)
add_sensors(fig, world, None)
fig.add_trace(
    go.Scatter(
        x=[None],
        y=[None],
        mode="markers",
        name="◆ sensör (sarı: arızalı, kırmızı: veri kaybı)",
        marker=dict(size=10, symbol="diamond", color="#ffffff", line=dict(color="#24292f", width=1.5)),
    )
)
fig.update_layout(
    height=560,
    margin=dict(l=10, r=10, t=10, b=10),
    legend=dict(orientation="v", x=1.01, y=1),
    plot_bgcolor="rgba(0,0,0,0)",
)
fig.update_xaxes(visible=False)
fig.update_yaxes(visible=False, scaleanchor="x", constrain="domain")
c_map, c_info = st.columns([3, 1])
c_map.plotly_chart(fig, width="stretch")
with c_info:
    st.metric("Park alanı (ızgara)", f"{len(world.veg_c) * world.cell_area_m2 / 10000:.1f} ha")
    st.metric("Sulama zonu", f"{len(world.zones)}")
    n_fault = sum(s.sensor.fault.type != "none" for s in world.sensors)
    st.metric("Sanal sensör", f"{len(world.sensors)}", help=f"{n_fault} tanesi arızalı üretildi.")
    st.caption(
        "Zonlar, park dört bloğa bölünüp her blokta bitki türüne göre ayrılarak oluşturuldu. Her zonun tek bir "
        "sulama sistemi var: çim ve çiçek tarhında yağmurlama, ağaçlık ve çalıda damla."
    )

# ------------------------------------------------------------------ gün gün
st.subheader("Gün gün: gerçek durum ve ikizin gördüğü")
dates = list(run.dates)
day = st.select_slider(
    "Gün",
    options=list(range(len(dates))),
    value=min(100, len(dates) - 1),
    format_func=lambda i: dates[i].strftime("%d %b %Y"),
)
raw_nominal = nominal_raw(world)
view = st.radio(
    "Haritada",
    ["İkizin kestirimi (zon başına)", "Sanal gerçek (hücre başına, ikizden gizli)"],
    horizontal=True,
)
hat_ratio = run.dr_hat[day] / raw_nominal
if view.startswith("İkiz"):
    cell_ratio = hat_ratio[world.zone_c]
else:
    cell_ratio = run.dr_true[day] / world.raw_c
true_zone = np.bincount(world.zone_c, weights=run.dr_true[day] / world.raw_c, minlength=len(world.zones)) / (
    np.bincount(world.zone_c, minlength=len(world.zones))
)
stressed_zone = np.bincount(world.zone_c, weights=run.ks[day] < 0.999, minlength=len(world.zones)) / (
    np.bincount(world.zone_c, minlength=len(world.zones))
)
zone_text = [
    f"<b>{zone_name(z)}</b> · {z.label}<br>ikiz: {STATE_LABELS[int(state_class(hat_ratio[zi], margin))]}"
    f" ({hat_ratio[zi]:.2f})<br>gerçek ort.: {true_zone[zi]:.2f} · stresli alan %{100 * stressed_zone[zi]:.0f}"
    for zi, z in enumerate(world.zones)
]
key = "zone_past"
default = int(np.argmax(stressed_zone))
sel = int(st.session_state.get(key, default)) % len(world.zones)
c_map, c_card = st.columns([3, 2], gap="medium")
with c_map:
    ev = st.plotly_chart(
        state_map(world, cell_ratio, margin, zone_text, selected=sel),
        width="stretch",
        on_select="rerun",
        selection_mode="points",
        key="map_past",
    )
    if pick_zone(ev, key, len(world.zones), default) != sel:
        st.rerun()
with c_card:
    zone_card(world, sel, run, weather, day, float(run.dr_hat[day, sel]), margin)
m1, m2, m3, m4 = st.columns(4)
m1.metric("ETo / yağış", f"{weather['eto_mm'].iloc[day]:.1f} / {weather['rain_mm'].iloc[day]:.1f} mm")
m2.metric("Strese giren alan", f"{100 * run.stressed_area_frac[day]:.0f} %")
m3.metric("Bugün verilen su (tüm sistemler)", f"{run.water_m3[day]:,.0f} m³")
m4.metric("Sezon başından beri", f"{run.water_m3[: day + 1].sum():,.0f} m³")
st.caption(
    "Haritada bir zona tıklayın. İkizin kestirimi zon başına tek değerdir; sanal gerçek her 10 m hücrenin durumudur. "
    "İkisi arasındaki fark ikizin hatası ve zon içi farklılıktır. Zon kartındaki sensör okuması seçili günden önceki "
    "günündür."
)

st.markdown(f"**{dates[day]:%d %B %Y} sulama kararı · {STRATEGIES[shown][0]}**")
mins = runtime_minutes(world, run.dose_mm[day])
decision = pd.DataFrame(
    {
        "zon": [z.zone_id for z in world.zones],
        "bitki": [z.label for z in world.zones],
        "sistem": [z.irrigation for z in world.zones],
        "alan (ha)": [round(z.area_m2 / 10000, 2) for z in world.zones],
        "ikizin gördüğü (açık/eşik)": np.round(run.dr_hat[day] / raw_nominal, 2),
        "gerçek ort. (açık/eşik)": np.round(
            np.bincount(world.zone_c, weights=run.dr_true[day] / world.raw_c, minlength=len(world.zones))
            / np.bincount(world.zone_c, minlength=len(world.zones)),
            2,
        ),
        "çalışma süresi (dk)": np.round(mins).astype(int),
        "su (m³)": np.round(run.dose_mm[day] * np.array([z.area_m2 for z in world.zones]) / 1000, 1),
    }
)
st.dataframe(decision.sort_values("çalışma süresi (dk)", ascending=False), width="stretch", hide_index=True)
st.caption(
    "Çalışma süresi = brüt doz / sistemin uygulama hızı. Sanal parkta bu karar sistemlere otomatik uygulanır; "
    "gerçek parkta karar mekanizması yalnız öneri üretir ve onay gerektirir (CLAUDE.md §2.3)."
)

# ------------------------------------------------------------------ strateji karşılaştırması
st.subheader("Sezon sonucu: dört yönetim, aynı park")
summ = pd.DataFrame({k: summarize_run(r) for k, r in runs.items()}).T
cols = st.columns(4)
for col, k in zip(cols, STRATEGIES):
    s = summ.loc[k]
    col.markdown(
        f'<div style="border-left:4px solid {STRAT_COLORS[k]}; padding-left:.6rem"><b>{STRATEGIES[k][0]}</b></div>',
        unsafe_allow_html=True,
    )
    col.metric("Su", f"{s.su_m3:,.0f} m³")
    col.metric("Strese giren alan (ort.)", f"{s.stresli_alan_ort_pct:.1f} %")
    col.metric("Derin sızma (kayıp)", f"{s.derin_sizma_m3:,.0f} m³")
    col.metric(
        "Kestirim hatası (RMSE)", "–" if np.isnan(s.kestirim_rmse_mm) else f"{s.kestirim_rmse_mm:.1f} mm"
    )

f3 = make_subplots(
    rows=1,
    cols=2,
    horizontal_spacing=0.08,
    subplot_titles=("Birikimli su (m³)", "Strese giren alan payı (%)"),
)
for k, r in runs.items():
    f3.add_trace(
        go.Scatter(
            x=r.dates,
            y=np.cumsum(r.water_m3),
            name=STRATEGIES[k][0],
            line=dict(color=STRAT_COLORS[k], width=2.5),
        ),
        row=1,
        col=1,
    )
    f3.add_trace(
        go.Scatter(
            x=r.dates,
            y=100 * r.stressed_area_frac,
            name=STRATEGIES[k][0],
            showlegend=False,
            line=dict(color=STRAT_COLORS[k], width=2),
        ),
        row=1,
        col=2,
    )
f3.update_layout(
    height=360,
    margin=dict(l=10, r=10, t=40, b=10),
    legend=dict(orientation="h", y=-0.15),
    hovermode="x unified",
)
st.plotly_chart(f3, width="stretch")
st.caption(
    "Bu sayılar sanal test dünyasının çıktısıdır, gerçek park ölçümü değildir (etiket: synthetic_world; hava: "
    f"{source}). Bir yönetimin iyi olması için hem az su hem az stres gerekir; yalnız suya bakmak yanıltır."
)

# ------------------------------------------------------------------ sensör ayrıntısı
st.subheader("Bir sensörü incele")
sensor_ids = [s.sensor.sensor_id for s in world.sensors]
default_idx = next((i for i, s in enumerate(world.sensors) if s.sensor.fault.type != "none"), 0)
sid = st.selectbox(
    "Sensör",
    sensor_ids,
    index=default_idx,
    format_func=lambda i: (
        f"{i} · {FAULT_TEXT.get(next(s.sensor.fault.type for s in world.sensors if s.sensor.sensor_id == i), '')}"
    ),
)
sd = run.sensors[run.sensors["sensor_id"] == sid]
f4 = go.Figure()
f4.add_trace(
    go.Scatter(
        x=sd["time"], y=sd["theta_true"], name="hücrenin gerçek nemi", line=dict(color="#24292f", width=2.5)
    )
)
f4.add_trace(
    go.Scatter(
        x=sd["time"],
        y=sd["theta_read"],
        name="sensör okuması",
        mode="markers",
        marker=dict(size=5, color="#8250df"),
    )
)
f4.update_layout(
    height=320,
    margin=dict(l=10, r=10, t=10, b=10),
    yaxis_title="Toprak nemi (m³/m³)",
    legend=dict(orientation="h", y=1.1),
)
st.plotly_chart(f4, width="stretch")

with st.expander("Sanal dünyanın varsayımları"):
    st.caption(world.spec["notes"])
    rows = []
    for k in VEG_KEYS:
        v = spec_veg[k]
        kc = v.get("kc_stage") or v.get("kc_range")
        rows.append(
            {
                "bitki": v["label"],
                "alan payı": v["fraction"],
                "Kc": str(kc),
                "Kc kaynağı": v["kc_source"],
                "kök derinliği (m)": str(v["root_depth_m"]),
                "p": v["p_depletion"],
                "sulama": v["irrigation"],
                "verim η": v["efficiency"],
                "zon başına sensör": v["sensors_per_zone"],
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.json({"toprak": world.spec["soil"], "sensörler": world.spec["sensors"]}, expanded=False)
st.caption("Akıllı Sulama Dijital İkizi · Galatasaray Üniversitesi · Bu ekran sulama komutu göndermez.")
