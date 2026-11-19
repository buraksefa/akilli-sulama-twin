"""Sanal Park Test Alanı (Streamlit).

Çalıştırma:  .venv/bin/streamlit run src/twin/ui/sanal_park.py

Aynı sanal parkta iki sulama stratejisini, gerçek ERA5 (yoksa etiketli sentetik) havası üzerinde
yan yana koşturur: ne kadar su harcandığını, bitkinin strese girip girmediğini ve teorik en az
suya ne kadar uzak kalındığını gösterir. Üretilen miktarlar yalnızca ÖNERİDİR; hiçbir aktüatöre
veya MQTT konusuna komut gönderilmez.
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
    "S0": ("Sabit takvim", "3 günde bir 12 mm. Bugünkü yaygın uygulamaya benzer; havaya bakmaz."),
    "S1": ("Sensör eşiği", "Sensör 'kuru' derse toprağı tarla kapasitesine kadar doldurur. Sensöre güvenir."),
    "S2": ("Yalnız hava (ET)", "Sensörsüz; hava verisiyle toprağın kuruduğunu hesaplar, eşikte doldurur."),
    "S3": ("Yağış tahminli", "S2 gibi; ertesi gün ≥ 5 mm yağış bekleniyorsa sulamayı erteler."),
    "S4": ("Asimile ikiz (EnKF)", "Model ile sensörü birleştirir (Kalman filtresi), eşikte doldurur."),
    "S5": (
        "Tam zamanında (önerilen)",
        "Her gün yalnızca toprağı stres eşiğinin hemen altında tutacak kadar su verir.",
    ),
}
COLOR_A, COLOR_B, COLOR_MIN = "#9a6700", "#0969da", "#57606a"

CSS = """
<style>
.block-container {padding-top: 2.2rem; max-width: 1250px;}
.step {border:1px solid rgba(128,128,128,.25); border-radius:10px; padding:.8rem 1rem; height:100%;}
.step b {display:block; margin-bottom:.25rem;}
.step span {opacity:.8; font-size:.9rem;}
.tag {display:inline-block; padding:.1rem .5rem; border-radius:999px; font-size:.8rem;
      border:1px solid rgba(128,128,128,.35); margin:0 .35rem .35rem 0;}
.lead {font-size:1.05rem; opacity:.85; margin-top:-.4rem;}
</style>
"""


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
    return run.zones, run.sensors, run.skipped, run.source


def season_summary(z: pd.DataFrame, oracle: pd.DataFrame) -> dict:
    w = z["advice_m3"].sum()
    w_min = oracle["advice_m3"].sum()
    return {
        "su_m3": w,
        "fazla_pct": 100.0 * (w - w_min) / w_min if w_min > 0 else np.nan,
        "stres_gunu": int(z.groupby("time")["ks"].min().lt(0.999).sum()),
    }


st.set_page_config(page_title="Sanal Park · Sulama Dijital İkizi", page_icon="🌿", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

scenarios = sorted(SCENARIO_DIR.glob("*.json"))
if not scenarios:
    st.error(f"Senaryo bulunamadı: {SCENARIO_DIR}")
    st.stop()

# ------------------------------------------------------------------ kenar çubuğu
with st.sidebar:
    st.subheader("Karşılaştırma")
    year = st.selectbox("Sezon (1 Nisan – 31 Ekim)", [2020, 2021, 2022, 2023, 2024], index=4)
    keys = list(STRATEGIES)
    key_a = st.selectbox(
        "A · mevcut yaklaşım", keys, index=0, format_func=lambda k: f"{k} · {STRATEGIES[k][0]}"
    )
    key_b = st.selectbox("B · alternatif", keys, index=5, format_func=lambda k: f"{k} · {STRATEGIES[k][0]}")
    with st.expander("İleri ayarlar"):
        margin = st.slider(
            "S5 güvenlik payı (hedef / stres eşiği)",
            0.6,
            1.0,
            0.9,
            0.05,
            help="1,0 = toprak tam eşikte tutulur; 0,9 = eşiğin %10 altında, küçük tahmin hatalarına karşı pay.",
        )
        seed = int(st.number_input("Sensör gürültüsü tohumu", 0, 9999, 0))
        sc_path = st.selectbox("Senaryo dosyası", scenarios, format_func=lambda p: p.name)
    st.caption(
        "Sensörleri karara yalnız S1 ve S4 katar. Diğerleri model durumuna dayanır; "
        "sensör arızası onları etkilemez."
    )

scenario = load_scenario(sc_path)
za, sa, skipped, source = run_sim(str(sc_path), year, key_a, margin, seed)
zb, _, _, _ = run_sim(str(sc_path), year, key_b, margin, seed)
zo, _, _, _ = run_sim(str(sc_path), year, "ORACLE", 1.0, seed)

# ------------------------------------------------------------------ başlık
st.title("Sanal Park Test Alanı")
st.markdown(
    '<p class="lead">Aynı park, aynı hava, iki farklı sulama kararı: hangisi daha az suyla bitkiyi '
    "susuz bırakmadan sezonu geçirir?</p>",
    unsafe_allow_html=True,
)
src_tag = "Hava: ERA5-Land (gerçek)" if source == "era5" else "Hava: SENTETİK"
st.markdown(
    f'<span class="tag">{src_tag}</span><span class="tag">Sezon {year}</span>'
    f'<span class="tag">Park planı: şematik varsayım</span><span class="tag">Çıktı: yalnız öneri</span>',
    unsafe_allow_html=True,
)

with st.expander("Bu simülasyon nasıl çalışır?", expanded=False):
    c = st.columns(4)
    steps = [
        ("1 · Hava", "Her gün ERA5-Land'den buharlaşma ihtiyacı (ETo) ve yağış."),
        (
            "2 · Toprak su deposu",
            "Kök bölgesi bir depo gibi: yağış ve sulama doldurur, bitki tüketir (FAO-56).",
        ),
        ("3 · Sanal sensörler", "Gerçek nemi gürültü ve arızalarla (kayma, donma, veri kaybı) ölçer."),
        ("4 · Karar", "Strateji o günün sulama önerisini verir; depo bir gün ilerler."),
    ]
    for col, (t, d) in zip(c, steps):
        col.markdown(f'<div class="step"><b>{t}</b><span>{d}</span></div>', unsafe_allow_html=True)
    st.markdown(
        "Depo **stres eşiğinin** altına inerse bitki susuz kalmaya başlar (stres günü). "
        "**Teorik en az su**, o günün havasını önceden bilen hayali bir yöneticinin stressiz kullanacağı "
        "sudur; hiçbir strateji stressiz kalarak bundan azını kullanamaz."
    )

if skipped:
    st.caption("Simüle edilmeyen zon: " + "; ".join(f"{k} ({v})" for k, v in skipped.items()) + ".")

# ------------------------------------------------------------------ sezon özeti
sum_a, sum_b, sum_o = season_summary(za, zo), season_summary(zb, zo), season_summary(zo, zo)
st.subheader("Sezon sonucu")
col_a, col_b = st.columns(2)
for col, k, s, color in ((col_a, key_a, sum_a, COLOR_A), (col_b, key_b, sum_b, COLOR_B)):
    with col:
        st.markdown(
            f'<div style="border-left:4px solid {color}; padding-left:.7rem; margin-bottom:.5rem">'
            f"<b>{k} · {STRATEGIES[k][0]}</b><br><span style='opacity:.8'>{STRATEGIES[k][1]}</span></div>",
            unsafe_allow_html=True,
        )
        m1, m2, m3 = st.columns(3)
        m1.metric("Su", f"{s['su_m3']:,.0f} m³", help="Simüle edilen zonların sezon toplamı (brüt).")
        m2.metric(
            "Teorik en aza göre",
            f"{s['fazla_pct']:+.0f} %",
            help="Negatifse strateji bitkiye gereken suyu vermemiştir (stres).",
        )
        m3.metric(
            "Stres günü", f"{s['stres_gunu']}", help="En az bir zonda bitkinin susuz kaldığı gün sayısı."
        )
diff = sum_a["su_m3"] - sum_b["su_m3"]
st.info(
    f"B, A'ya göre **{abs(diff):,.0f} m³ {'daha az' if diff >= 0 else 'daha fazla'}** su kullanıyor "
    f"({-100 * diff / sum_a['su_m3']:+.0f} %). Stres günü: A {sum_a['stres_gunu']}, B {sum_b['stres_gunu']}. "
    f"Teorik en az su: {sum_o['su_m3']:,.0f} m³."
)

# ------------------------------------------------------------------ birikimli su
st.subheader("Sezon boyunca harcanan su")
fig = go.Figure()
series = ((za, key_a, COLOR_A, None), (zb, key_b, COLOR_B, None), (zo, None, COLOR_MIN, "dot"))
for z, k, color, dash in series:
    cum = z.groupby("time")["advice_m3"].sum().cumsum()
    name = "Teorik en az" if k is None else f"{k} · {STRATEGIES[k][0]}"
    fig.add_trace(
        go.Scatter(x=cum.index, y=cum.values, name=name, line=dict(color=color, width=3, dash=dash))
    )
rain = za.groupby("time")["rain_mm"].first()
fig.add_trace(
    go.Bar(x=rain.index, y=rain.values, name="Yağış (mm)", yaxis="y2", marker_color="rgba(9,105,218,.25)")
)
fig.update_layout(
    height=380,
    margin=dict(l=10, r=10, t=10, b=10),
    yaxis=dict(title="Birikimli su (m³)"),
    yaxis2=dict(
        title="Yağış (mm)", overlaying="y", side="right", showgrid=False, range=[0, max(60, rain.max() * 3)]
    ),
    legend=dict(orientation="h", y=1.08),
    hovermode="x unified",
)
st.plotly_chart(fig, width="stretch")
st.caption(
    "Çizgiler arasındaki açıklık, aynı hava altında stratejiler arasındaki su farkıdır. "
    "Yağışlı günlerden sonra sabit takvim sulamaya devam eder; fazla su toprağın altına sızarak kaybolur."
)

# ------------------------------------------------------------------ oynatılabilir depo
st.subheader("Toprak su deposu, gün gün")
sim_zones = [z for z in scenario.zones if z.zone_id in set(za["zone_id"])]
labels = [f"{z.zone_id} · {z.name}" for z in sim_zones]
r0 = za[za["zone_id"] == sim_zones[0].zone_id].iloc[0]
taw, raw = float(r0.taw_mm), float(r0.raw_mm)
dates = sorted(za["time"].unique())
ia = za.set_index(["time", "zone_id"])
ib = zb.set_index(["time", "zone_id"])


def bars(t):
    out = []
    for frame_df, k, color in ((ia, key_a, COLOR_A), (ib, key_b, COLOR_B)):
        rows = [frame_df.loc[(t, z.zone_id)] for z in sim_zones]
        out.append(
            go.Bar(
                x=labels,
                y=[taw - r.dr_start_mm for r in rows],
                name=f"{k} · {STRATEGIES[k][0]}",
                marker_color=color,
                text=[f"💧 {r.advice_gross_mm:.0f} mm" if r.advice_gross_mm > 0.1 else "" for r in rows],
                textposition="outside",
                hovertemplate="%{x}<br>depodaki su: %{y:.1f} mm<extra>" + k + "</extra>",
            )
        )
    return out


frames = [go.Frame(data=bars(t), name=pd.Timestamp(t).strftime("%d %b")) for t in dates]
fig2 = go.Figure(data=bars(dates[0]), frames=frames)
lines = (
    (taw, "tarla kapasitesi (dolu)", "dot"),
    (taw - raw, "stres eşiği", "dash"),
    (0, "solma noktası (boş)", "dot"),
)
for y, txt, dash in lines:
    fig2.add_hline(
        y=y, line_dash=dash, line_color="#cf222e" if "stres" in txt else "#8c959f", annotation_text=txt
    )
play = dict(frame=dict(duration=120, redraw=True), fromcurrent=True)
pause = dict(mode="immediate", frame=dict(duration=0))
fig2.update_layout(
    height=440,
    barmode="group",
    bargap=0.35,
    margin=dict(l=10, r=10, t=30, b=10),
    yaxis=dict(title="Kökün kullanabileceği su (mm)", range=[0, taw * 1.25]),
    legend=dict(orientation="h", y=1.12),
    updatemenus=[
        dict(
            type="buttons",
            x=0,
            y=-0.12,
            xanchor="left",
            direction="left",
            buttons=[
                dict(label="▶ Oynat", method="animate", args=[None, play]),
                dict(label="❚❚ Durdur", method="animate", args=[[None], pause]),
            ],
        )
    ],
    sliders=[
        dict(
            x=0.18,
            len=0.82,
            y=-0.08,
            currentvalue=dict(prefix="Gün: "),
            steps=[
                dict(
                    label=f.name,
                    method="animate",
                    args=[[f.name], dict(mode="immediate", frame=dict(duration=0))],
                )
                for f in frames
            ],
        )
    ],
)
st.plotly_chart(fig2, width="stretch")
st.caption(
    "Sütun, kökün kullanabileceği suyu gösterir. Kırmızı kesikli çizginin altı stres demektir. "
    "Damla simgesi o günkü sulama önerisidir. ▶ ile sezonu izleyin."
)

# ------------------------------------------------------------------ sensörler
st.subheader("Sanal sensörler: arıza kararı nasıl yanıltır?")
zone_opts = {z.zone_id: z for z in sim_zones}
zid = st.selectbox("Zon", list(zone_opts), format_func=lambda i: f"{i} · {zone_opts[i].name}")
zone = zone_opts[zid]
fault_text = {
    "none": "sağlam",
    "drift": "zamanla kayıyor (toprağı olduğundan ıslak gösterir)",
    "freeze": "bir süre donuyor (aynı değeri tekrar eder)",
    "bias": "sabit sapmalı",
    "dropout": "zaman zaman veri göndermiyor",
}
st.markdown(
    " · ".join(f"**{s.sensor_id}**: {fault_text.get(s.fault.type, s.fault.type)}" for s in zone.sensors)
)
zd = za[za["zone_id"] == zid]
sd = sa[sa["zone_id"] == zid]
f3 = go.Figure()
f3.add_trace(
    go.Scatter(
        x=zd["time"],
        y=zd["theta_start"],
        name=f"gerçek nem ({key_a} ile sulanan zon)",
        line=dict(color="#24292f", width=3),
    )
)
for sid, g in sd.groupby("sensor_id"):
    f3.add_trace(
        go.Scatter(x=g["time"], y=g["theta_read"], name=f"{sid} okuması", mode="markers", marker=dict(size=5))
    )
theta_stress = float(zd.iloc[0].theta_fc - (raw / taw) * (zd.iloc[0].theta_fc - zd.iloc[0].theta_wp))
f3.add_hline(y=theta_stress, line_dash="dash", line_color="#cf222e", annotation_text="stres eşiği")
f3.update_layout(
    height=340,
    margin=dict(l=10, r=10, t=10, b=10),
    yaxis_title="Toprak nemi (m³/m³)",
    legend=dict(orientation="h", y=1.1),
)
st.plotly_chart(f3, width="stretch")
uses_sensor = [k for k in (key_a, key_b) if k in ("S1", "S4")]
if uses_sensor:
    st.caption(
        f"{', '.join(uses_sensor)} kararını bu okumaların ortalamasına göre verir; kayan ya da donan sensör yanıltır."
    )
else:
    st.caption(
        "Seçili stratejiler sensörü karara katmıyor. Sensör arızasının etkisini görmek için A ya da B'ye "
        "S1 veya S4 seçin."
    )


# ------------------------------------------------------------------ teknik ayrıntılar
def per_zone(z: pd.DataFrame, label: str) -> pd.DataFrame:
    g = z.groupby("zone_id").agg(
        su_mm=("advice_gross_mm", "sum"),
        su_m3=("advice_m3", "sum"),
        stres_gunu=("ks", lambda k: int((k < 0.999).sum())),
        sizma_mm=("dp_mm", "sum"),
    )
    g.insert(0, "strateji", label)
    return g


with st.expander("Zon bazında tablo"):
    tab = pd.concat([per_zone(za, key_a), per_zone(zb, key_b), per_zone(zo, "Teorik en az")])
    tab["kaynak"] = source
    st.dataframe(tab.round(1), width="stretch")
with st.expander("Parametreler ve kaynakları"):
    inv = parameter_inventory(scenario)
    inv["değer"] = inv["değer"].astype(str)
    st.caption(scenario.notes)
    st.dataframe(inv, width="stretch", hide_index=True)
st.caption(
    "Akıllı Sulama Dijital İkizi · Galatasaray Üniversitesi · Yöntem: docs/model/VERIMLILIK_MODELI.md. "
    "Bu ekran sulama komutu göndermez."
)
