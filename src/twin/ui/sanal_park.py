"""Sanal Park Test Alanı (Streamlit).

Çalıştırma:  .venv/bin/streamlit run src/twin/ui/sanal_park.py

Fiziksel kuruluma geçmeden önce: senaryo dosyasındaki zonlar ve sanal sensörlerle, gerçek ERA5
(yoksa etiketli sentetik) hava üzerinde gün gün simülasyon. Üretilen sulama miktarları yalnızca
ÖNERİDİR; hiçbir aktüatöre veya MQTT konusuna komut gönderilmez.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from twin.sim.efficiency import OracleJustInTime
from twin.sim.engine import prepare_season_weather
from twin.sim.learned_policy import PersistenceJIT
from twin.sim.strategies import get_all_strategies
from twin.sim.virtual_park import load_scenario, parameter_inventory, simulate_virtual_park

ROOT = Path(__file__).resolve().parents[3]
SCENARIO_DIR = ROOT / "data" / "scenarios"

STRATEGIES = {
    "S5": "S5 · Kalıcılık JIT (güvenlik paylı)",
    "S0": "S0 · Sabit takvim",
    "S1": "S1 · Sensör eşiği",
    "S2": "S2 · Yalnız ET",
    "S3": "S3 · Yağış tahminli",
    "S4": "S4 · Asimile ikiz (EnKF)",
    "ORACLE": "Kâhin · teorik alt sınır (uygulanamaz)",
}


def make_factory(key: str, margin: float):
    def factory(_zone_id: str):
        if key == "S5":
            return PersistenceJIT(margin)
        if key == "ORACLE":
            return OracleJustInTime()
        return get_all_strategies()[key]

    return factory


@st.cache_data(show_spinner="Sanal park simüle ediliyor…")
def run_sim(scenario_path: str, year: int, key: str, margin: float, seed: int):
    sc = load_scenario(scenario_path)
    weather = prepare_season_weather(season_year=year, source="auto", park_id=sc.park_id)
    run = simulate_virtual_park(sc, weather, make_factory(key, margin), seed=seed)
    oracle = simulate_virtual_park(sc, weather, make_factory("ORACLE", 1.0), seed=seed)
    return run.zones, run.sensors, run.skipped, run.source, oracle.zones


def moisture_color(frac_of_taw: float, raw_frac: float) -> str:
    """Dr/TAW oranına göre renk: RAW altı yeşil, RAW-TAW arası sarıdan kırmızıya."""
    if frac_of_taw <= raw_frac:
        g = 0.35 + 0.4 * (frac_of_taw / max(raw_frac, 1e-6))
        return f"rgba(46,160,67,{0.85 - 0.4 * g:.2f})"
    t = min(1.0, (frac_of_taw - raw_frac) / max(1.0 - raw_frac, 1e-6))
    r, g = 230, int(180 * (1 - t))
    return f"rgba({r},{g},40,0.75)"


st.set_page_config(page_title="Sanal Park Test Alanı", page_icon="🌳", layout="wide")
st.title("🌳 Sanal Park Test Alanı")
st.caption("Fiziksel kurulumdan önce dijital test: sanal zonlar, sanal sensörler, gerçek ERA5 havası.")

scenarios = sorted(SCENARIO_DIR.glob("*.json"))
if not scenarios:
    st.error(f"Senaryo bulunamadı: {SCENARIO_DIR}")
    st.stop()

with st.sidebar:
    st.header("Senaryo")
    sc_path = st.selectbox("Senaryo dosyası", scenarios, format_func=lambda p: p.name)
    year = st.selectbox("Sezon (Nisan-Ekim)", [2020, 2021, 2022, 2023, 2024], index=4)
    key = st.selectbox("Strateji (tüm zonlar)", list(STRATEGIES), format_func=STRATEGIES.get)
    margin = 0.9
    if key == "S5":
        margin = st.slider("Güvenlik payı: hedef D / RAW", 0.6, 1.0, 0.9, 0.05)
    seed = st.number_input("Sensör gürültüsü tohumu", 0, 9999, 0)
    st.caption(
        "Sanal sensörleri karar için yalnız **S1** ve **S4** kullanır. S0, S2, S3, S5 ve kâhin model "
        "durumuna dayanır; bu stratejilerde sensör arızası karara yansımaz, yalnız grafikte görünür."
    )

scenario = load_scenario(sc_path)
zones_df, sensors_df, skipped, source, oracle_df = run_sim(str(sc_path), year, key, margin, int(seed))

src_label = "🛰️ ERA5-Land (gerçek)" if source == "era5" else "🧪 SENTETİK hava"
st.info(
    f"**Hava verisi:** {src_label} · **Senaryo durumu:** `{scenario.status}` · {scenario.notes}",
    icon="ℹ️",
)
if skipped:
    st.warning("Simüle edilmeyen zonlar: " + "; ".join(f"**{k}**: {v}" for k, v in skipped.items()))

dates = sorted(zones_df["time"].unique())
day = st.select_slider(
    "Gün",
    options=list(range(len(dates))),
    value=min(105, len(dates) - 1),
    format_func=lambda i: pd.Timestamp(dates[i]).strftime("%d %b %Y"),
)
today = dates[day]
z_today = zones_df[zones_df["time"] == today].set_index("zone_id")
s_today = sensors_df[sensors_df["time"] == today]
upto = zones_df[zones_df["time"] <= today]

first = z_today.iloc[0] if len(z_today) else None
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("ETo", f"{first.eto_mm:.2f} mm" if first is not None else "-")
c2.metric("Yağış", f"{first.rain_mm:.1f} mm" if first is not None else "-")
c3.metric("Bugünkü öneri", f"{z_today['advice_m3'].sum():.0f} m³")
c4.metric("Sezon toplamı", f"{upto['advice_m3'].sum():,.0f} m³")
c5.metric("Stresli zon", f"{int((z_today['ks'] < 0.999).sum())} / {len(z_today)}")

# ---------------------------------------------------------------- park haritası
fig = go.Figure()
for z in scenario.zones:
    x, y, w, h = z.layout
    if z.zone_id in z_today.index:
        r = z_today.loc[z.zone_id]
        fill = moisture_color(r.dr_start_mm / r.taw_mm, r.raw_mm / r.taw_mm)
        label = (
            f"<b>{z.zone_id} · {z.name}</b><br>θ {r.theta_start:.3f} m³/m³ · Dr {r.dr_start_mm:.1f}/{r.raw_mm:.0f} mm"
            f"<br>Öneri: {r.advice_gross_mm:.1f} mm ({r.advice_m3:.1f} m³)"
        )
    else:
        fill = "rgba(150,150,150,0.35)"
        label = f"<b>{z.zone_id} · {z.name}</b><br>simüle edilmiyor (profil yok)"
    fig.add_shape(
        type="rect", x0=x, y0=y, x1=x + w, y1=y + h, fillcolor=fill, line=dict(color="#444", width=1)
    )
    fig.add_annotation(
        x=x + 1,
        y=y + h - 1,
        text=label,
        showarrow=False,
        xanchor="left",
        yanchor="top",
        align="left",
        bgcolor="rgba(255,255,255,0.75)",
        font=dict(color="#111"),
    )

status_color = {"ok": "#1a7f37", "arızalı": "#d4a72c", "veri yok": "#cf222e"}
for z in scenario.zones:
    for s in z.sensors:
        row = s_today[s_today["sensor_id"] == s.sensor_id]
        if row.empty:
            stt, txt = "veri yok", f"{s.sensor_id}: zon simüle edilmiyor"
        else:
            rr = row.iloc[0]
            if np.isnan(rr.theta_read):
                stt = "veri yok"
            elif rr.fault_active:
                stt = "arızalı"
            else:
                stt = "ok"
            txt = f"{s.sensor_id} ({s.fault.type})<br>okuma {rr.theta_read:.3f} · gerçek {rr.theta_true:.3f}"
        fig.add_trace(
            go.Scatter(
                x=[s.pos[0]],
                y=[s.pos[1]],
                mode="markers+text",
                marker=dict(size=18, color=status_color[stt], line=dict(color="#111", width=2)),
                text=[s.sensor_id],
                textposition="bottom center",
                hovertext=[txt],
                hoverinfo="text",
                showlegend=False,
            )
        )
cw, ch = scenario.canvas
fig.update_xaxes(range=[0, cw], visible=False)
fig.update_yaxes(range=[0, ch], visible=False)
fig.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10), font=dict(size=11))
st.plotly_chart(fig, width="stretch")
st.caption(
    "Harita şematiktir. Zon rengi: yeşil = stressiz (Dr ≤ RAW), sarı→kırmızı = stres. "
    "Sensör: yeşil = sağlam, sarı = arıza etkin, kırmızı = veri yok."
)

tab_zone, tab_sum, tab_adv, tab_par = st.tabs(
    ["📈 Zon ayrıntısı", "📊 Sezon özeti", "💧 Günlük öneriler", "📚 Parametre kaynakları"]
)

with tab_zone:
    sim_ids = list(z_today.index)
    if not sim_ids:
        st.write("Simüle edilen zon yok.")
    else:
        zid = st.selectbox("Zon", sim_ids)
        zd = zones_df[zones_df["zone_id"] == zid]
        sd = sensors_df[sensors_df["zone_id"] == zid]
        r0 = zd.iloc[0]
        theta_raw = r0.theta_fc - (r0.raw_mm / r0.taw_mm) * (r0.theta_fc - r0.theta_wp)
        f2 = go.Figure()
        f2.add_trace(go.Scatter(x=zd["time"], y=zd["theta_start"], name="gerçek θ", line=dict(width=3)))
        for sid, g in sd.groupby("sensor_id"):
            f2.add_trace(
                go.Scatter(
                    x=g["time"], y=g["theta_read"], name=f"{sid} okuma", mode="markers", marker=dict(size=4)
                )
            )
        f2.add_hline(y=r0.theta_fc, line_dash="dot", annotation_text="tarla kapasitesi")
        f2.add_hline(y=theta_raw, line_dash="dash", annotation_text="stres eşiği (RAW)")
        f2.add_hline(y=r0.theta_wp, line_dash="dot", annotation_text="solma noktası")
        f2.add_vline(x=today, line_color="gray")
        f2.update_layout(height=360, yaxis_title="θ [m³/m³]", margin=dict(t=20))
        st.plotly_chart(f2, width="stretch")
        f3 = go.Figure()
        f3.add_trace(go.Bar(x=zd["time"], y=zd["advice_gross_mm"], name="sulama önerisi [mm]"))
        f3.add_trace(go.Bar(x=zd["time"], y=zd["rain_mm"], name="yağış [mm]"))
        f3.add_vline(x=today, line_color="gray")
        f3.update_layout(height=260, barmode="group", margin=dict(t=20))
        st.plotly_chart(f3, width="stretch")

with tab_sum:

    def summarize(df):
        return df.groupby("zone_id").agg(
            sulama_mm=("advice_gross_mm", "sum"),
            sulama_m3=("advice_m3", "sum"),
            stres_gunu=("ks", lambda k: int((k < 0.999).sum())),
            stres_siddeti=("ks", lambda k: float((1 - k).clip(lower=0).sum())),
            derin_sizma_mm=("dp_mm", "sum"),
        )

    summ = summarize(zones_df)
    summ["kahin_mm"] = summarize(oracle_df)["sulama_mm"]
    summ["kahine_gore_fazla_mm"] = summ["sulama_mm"] - summ["kahin_mm"]
    summ["kaynak"] = source
    st.dataframe(summ.round(2), width="stretch")
    st.caption(
        "Kâhin: o günün havasını bilen teorik alt sınır (docs/model/VERIMLILIK_MODELI.md). "
        "m³ değerleri senaryo alanlarına dayanır ve varsayımdır."
    )

with tab_adv:
    adv = z_today[["advice_gross_mm", "advice_m3", "dr_start_mm", "raw_mm", "sensor_obs"]].copy()
    adv.insert(0, "zon", [next(z.name for z in scenario.zones if z.zone_id == i) for i in adv.index])
    adv["durum"] = np.where(adv["advice_gross_mm"] > 0, "ÖNERİ · onay gerekli", "sulama yok")
    st.dataframe(adv.round(3), width="stretch")
    st.caption("Bu ekran yalnızca öneri üretir; vana/pompa komutu göndermez (CLAUDE.md §2.3).")

with tab_par:
    inv = parameter_inventory(scenario)
    inv["değer"] = inv["değer"].astype(str)
    counts = inv["durum"].value_counts()
    st.write("Durum dağılımı: " + ", ".join(f"`{k}`: {v}" for k, v in counts.items()))
    st.dataframe(inv, width="stretch", hide_index=True)
    st.caption(
        "`assumption` / `to_verify` / `missing` satırları kurum verisi (İBB, İSKİ, saha ölçümü) geldikçe "
        "senaryo dosyasında veya src/twin/config.py'de güncellenecek."
    )
