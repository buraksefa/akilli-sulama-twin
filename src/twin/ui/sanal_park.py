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


@st.cache_resource(show_spinner="Sanal park üretiliyor…")
def get_world(world_seed: int):
    spec = load_world_spec(SPEC_PATH)
    spec["world_seed"] = world_seed
    return build_world(spec, GEOJSON)


@st.cache_data(show_spinner="Sezon simüle ediliyor…")
def get_runs(world_seed: int, year: int, margin: float, sensor_seed: int):
    world = get_world(world_seed)
    weather = prepare_season_weather(season_year=year, source="auto", park_id=world.spec["park_id"])
    runs = {k: run_world(world, weather, k, margin=margin, sensor_seed=sensor_seed) for k in STRATEGIES}
    return runs, weather


@st.cache_data(ttl=3600, show_spinner="Hava tahmini alınıyor (Open-Meteo)…")
def get_forecast(day_key: str):
    era5 = TwinConfig().era5
    return fetch_open_meteo_daily(float(era5.yildiz_lat.value), float(era5.yildiz_lon.value))


@st.cache_data(ttl=3600, show_spinner="İkiz bugüne getiriliyor ve plan yapılıyor…")
def get_plans(world_seed: int, day_key: str, margin: float, sensor_seed: int):
    world = get_world(world_seed)
    wx = get_forecast(day_key)
    out = {}
    for k in STRATEGIES:
        _, plan = plan_from_forecast(world, wx, k, margin=margin, sensor_seed=sensor_seed)
        out[k] = plan
    return out, wx


def render_forecast(world, shown: str, margin: float, sensor_seed: int, world_seed: int):
    """Bugün ve önümüzdeki 7 gün: tahmine dayalı sulama planı."""
    day_key = pd.Timestamp.now(tz="Europe/Istanbul").strftime("%Y-%m-%d")
    try:
        plans, wx = get_plans(world_seed, day_key, margin, sensor_seed)
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
        '<span class="tag">Geçmiş 92 gün: Open-Meteo model analizi</span>'
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
    recent = wx[wx.index >= pd.Timestamp(today) - pd.Timedelta(days=14)]
    fw = make_subplots(specs=[[{"secondary_y": True}]])
    past_mask = ~recent["is_forecast"]
    fw.add_trace(
        go.Bar(
            x=recent.index[past_mask],
            y=recent["rain_mm"][past_mask],
            name="yağış (gerçekleşen)",
            marker_color="#7aa6d6",
        ),
        secondary_y=False,
    )
    fc_rows = recent[recent["is_forecast"]]
    fw.add_trace(
        go.Bar(
            x=fc_rows.index,
            y=fc_rows["rain_mm"],
            name="yağış tahmini (olasılık %)",
            marker_color="#0969da",
            text=[f"%{p:.0f}" for p in fc_rows["rain_prob_pct"]],
            textposition="outside",
            marker_opacity=[max(0.25, p / 100) for p in fc_rows["rain_prob_pct"]],
        ),
        secondary_y=False,
    )
    fw.add_trace(
        go.Scatter(
            x=recent.index,
            y=recent["eto_mm"],
            name="ETo (buharlaşma ihtiyacı)",
            line=dict(color="#cf6a00", width=3),
        ),
        secondary_y=True,
    )
    fw.add_vline(x=pd.Timestamp(today), line_dash="dash", line_color="#57606a")
    fw.add_annotation(x=pd.Timestamp(today), y=1.05, yref="paper", text="bugün", showarrow=False)
    fw.update_yaxes(title_text="Yağış (mm)", secondary_y=False)
    fw.update_yaxes(title_text="ETo (mm/gün)", secondary_y=True, showgrid=False)
    fw.update_layout(
        height=330, margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h", y=-0.2), bargap=0.25
    )
    st.plotly_chart(fw, width="stretch")

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

    # bugünkü durum ve bugünkü karar haritası
    st.subheader(f"Bugünkü durum ve karar · {STRATEGIES[shown][0]}")
    today_rows = plan[plan["time"] == today].set_index("zone")
    ratio = np.array([today_rows.loc[z.zone_id, "deficit_ratio_today"] for z in world.zones])
    fig = go.Figure()
    fig.add_trace(
        go.Heatmap(
            x=world.x,
            y=world.y,
            z=np.clip(world.to_grid(ratio[world.zone_c]), 0, 2),
            zmin=0,
            zmax=2,
            colorscale=STRESS_SCALE,
            colorbar=dict(title="açık / eşik", tickvals=[0, 1, 2], ticktext=["dolu", "eşik", "ağır stres"]),
            hovertemplate="ikizin kestirimi: %{z:.2f}<extra></extra>",
        )
    )
    for zi, z in enumerate(world.zones):
        cells = world.cell_rc[world.zone_c == zi]
        mins = today_rows.loc[z.zone_id, "minutes"]
        fig.add_trace(
            go.Scatter(
                x=[world.x[cells[:, 1]].mean()],
                y=[world.y[cells[:, 0]].mean()],
                mode="text",
                text=[f"{z.zone_id}<br>{mins:.0f} dk" if mins >= 0.5 else z.zone_id],
                textfont=dict(size=10, color="#111"),
                hoverinfo="skip",
                showlegend=False,
            )
        )
    add_boundary(fig, world)
    add_sensors(fig, world, None)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, scaleanchor="x", constrain="domain")
    fig.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, width="stretch")
    st.caption(
        "Renk: ikizin sanal sensörlerden kestirdiği bugünkü toprak nemi. Etiket: bugün planlanan çalışma süresi."
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
    with st.expander("Rastgelelik"):
        world_seed = int(st.number_input("Sanal park tohumu (bitki/toprak dağılımı)", 0, 9999, 7))
        sensor_seed = int(st.number_input("Sensör gürültüsü tohumu", 0, 9999, 0))
    st.caption("Tohumu değiştirmek yeni bir rastgele park ya da yeni sensör gürültüsü üretir.")

world = get_world(world_seed)
if mode.startswith("Bugün"):
    render_forecast(world, shown, margin, sensor_seed, world_seed)
    st.stop()
runs, weather = get_runs(world_seed, year, margin, sensor_seed)
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
stress_true = world.to_grid(run.dr_true[day] / world.raw_c)
hat_cells = run.dr_hat[day][world.zone_c]
raw_nominal = np.array(
    [
        z.p_nominal
        * 1000
        * (world.spec["soil"]["theta_fc"]["mean"] - world.spec["soil"]["theta_wp"]["mean"])
        * z.zr_nominal
        for z in world.zones
    ]
)
stress_hat = world.to_grid(hat_cells / raw_nominal[world.zone_c])
day_rows = run.sensors[run.sensors["time"] == dates[day]]

f2 = make_subplots(
    rows=1,
    cols=2,
    horizontal_spacing=0.03,
    subplot_titles=(
        "Gerçek toprak durumu (sanal dünya, ikizden gizli)",
        f"İkizin kestirimi · {STRATEGIES[shown][0]}",
    ),
)
for col, zgrid in ((1, stress_true), (2, stress_hat)):
    f2.add_trace(
        go.Heatmap(
            x=world.x,
            y=world.y,
            z=np.clip(zgrid, 0, 2),
            zmin=0,
            zmax=2,
            colorscale=STRESS_SCALE,
            showscale=col == 2,
            colorbar=dict(title="açık / eşik", tickvals=[0, 1, 2], ticktext=["dolu", "eşik", "ağır stres"]),
            hovertemplate="açık/eşik: %{z:.2f}<extra></extra>",
        ),
        row=1,
        col=col,
    )
    add_boundary(f2, world, row=1, col=col)
    add_sensors(f2, world, day_rows, row=1, col=col)
f2.update_xaxes(visible=False)
f2.update_yaxes(visible=False)
f2.update_yaxes(scaleanchor="x", constrain="domain", row=1, col=1)
f2.update_yaxes(scaleanchor="x2", constrain="domain", row=1, col=2)
f2.update_layout(height=520, margin=dict(l=10, r=10, t=40, b=10), plot_bgcolor="rgba(0,0,0,0)")
st.plotly_chart(f2, width="stretch")
m1, m2, m3, m4 = st.columns(4)
m1.metric("ETo / yağış", f"{weather['eto_mm'].iloc[day]:.1f} / {weather['rain_mm'].iloc[day]:.1f} mm")
m2.metric("Strese giren alan", f"{100 * run.stressed_area_frac[day]:.0f} %")
m3.metric("Bugün verilen su (tüm sistemler)", f"{run.water_m3[day]:,.0f} m³")
m4.metric("Sezon başından beri", f"{run.water_m3[: day + 1].sum():,.0f} m³")
st.caption(
    "Renk: mavi = toprak dolu, sarı = stres eşiğine yakın, kırmızı = bitki susuz. Sol harita her hücrenin gerçek durumu; "
    "sağ harita ikizin zon başına tek bir tahmini. İki harita arasındaki fark, ikizin hatasıdır."
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
