"""Cihazlar: sensör düğümlerinin canlı durumu, ölçüm geçmişi, kalite kontrol ve uyarılar.

Veri kaynağı:
- `TWIN_DEVICE_DB` (ya da data/devices/telemetry.sqlite) varsa: MQTT alım servisinin canlı deposu.
- Yoksa (ör. Streamlit Cloud): son 48 saat sanal düğümlerle aracısız üretilir ve DEMO olarak etiketlenir.

Gerçek ve sanal düğüm aynı sözleşmeyi kullanır; her satırda `sim` bayrağı vardır. Bu sayfa hiçbir komut göndermez.
"""

import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st
from plotly.subplots import make_subplots

from twin.config import TwinConfig
from twin.devices.registry import load_registry
from twin.devices.schema import err_text, topic_for
from twin.devices.store import TelemetryStore, db_path
from twin.qc.online import QC_REASONS

ROOT = Path(__file__).resolve().parents[4]
TZ = "Europe/Istanbul"
CFG = TwinConfig().devices
STATE_DOT = {"online": "🟢", "late": "🟡", "offline": "🔴", "never": "⚪"}
STATE_TEXT = {"online": "çevrimiçi", "late": "gecikti", "offline": "çevrimdışı", "never": "veri yok"}
ALERT_ICON = {
    "offline": "📴",
    "battery_low": "🪫",
    "rssi_weak": "📶",
    "device_error": "⚠️",
    "qc_reject": "🧪",
    "unknown_device": "❓",
    "bad_payload": "🧩",
}

st.set_page_config(page_title="Cihazlar · Sulama Dijital İkizi", page_icon="📡", layout="wide")
st.markdown(
    """<style>
    .block-container {padding-top: 2.2rem; max-width: 1300px;}
    .tag {display:inline-block; padding:.1rem .55rem; border-radius:999px; font-size:.8rem;
          border:1px solid rgba(128,128,128,.35); margin:0 .35rem .35rem 0;}
    .card {border:1px solid rgba(128,128,128,.25); border-radius:12px; padding:.7rem .9rem;}
    </style>""",
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner="Sanal düğümler son 48 saati üretiyor…", ttl=3600)
def demo_store(hour_key: str) -> str:
    from twin.devices.ingest import Ingestor
    from twin.devices.service import backfill, load_world, make_simulator

    path = Path(tempfile.gettempdir()) / f"twin_demo_{hour_key}.sqlite"
    if path.exists():
        return str(path)
    devices = load_registry(ROOT / "data/devices/registry.json")
    step = int(CFG.report_interval_s.value)
    end = pd.Timestamp.now(tz=TZ).floor(f"{step}s").to_pydatetime()
    tmp = path.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    store = TelemetryStore(str(tmp))
    backfill(
        make_simulator(load_world(ROOT), devices),
        Ingestor(store, devices),
        end - timedelta(hours=48),
        end,
        step,
    )
    store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    store.conn.execute("PRAGMA journal_mode=DELETE")
    store.close()
    tmp.replace(path)  # yalnız başarıyla biten depo yayımlanır (yarım dosya önbelleğe girmez)
    return str(path)


live_path = db_path()
if not live_path.is_absolute():
    live_path = ROOT / live_path
live = live_path.exists()
if live:
    store_path, source_tag = str(live_path), "Canlı: MQTT alım servisi"
else:
    try:
        store_path = demo_store(pd.Timestamp.now(tz=TZ).strftime("%Y%m%d%H"))
    except Exception as e:
        st.title("Cihazlar")
        st.error(
            "Canlı depo yok ve demo verisi üretilemedi: hava servisine (Open-Meteo) ulaşılamadı. "
            f"Birkaç dakika sonra sayfayı yenileyin.\n\nAyrıntı: {e}"
        )
        st.stop()
    source_tag = "DEMO: sanal düğümler, son 48 saat (canlı bağlantı yok)"

devices = load_registry(ROOT / "data/devices/registry.json")
dev_by_node = {d.node: d for d in devices}

st.title("Cihazlar")
st.markdown(
    f'<span class="tag">{source_tag}</span><span class="tag">Kayıt: {len(devices)} düğüm '
    f"({sum(d.source == 'real' for d in devices)} gerçek, {sum(d.source == 'simulated' for d in devices)} sanal)</span>"
    f'<span class="tag">Rapor aralığı: {CFG.report_interval_s.value // 60:.0f} dk</span>'
    '<span class="tag">Komut gönderilmez (yalnız izleme ve öneri)</span>',
    unsafe_allow_html=True,
)


def node_state(last_received, status, now):
    if last_received is None or np.isnan(last_received):
        return "never"
    age = now - last_received
    limit = CFG.offline_after_intervals.value * CFG.report_interval_s.value
    if status == "offline" and age > CFG.report_interval_s.value:
        return "offline"
    if age > limit:
        return "offline"
    if age > 1.5 * CFG.report_interval_s.value:
        return "late"
    return "online"


@st.fragment(run_every="60s" if live else None)
def dashboard():
    store = TelemetryStore(store_path, read_only=True)
    now = time.time() if live else float(store.latest()["received"].max() or time.time())
    latest = store.latest().set_index("node")
    status = store.status().set_index("node")["state"].to_dict() if len(store.status()) else {}
    qc = store.qc_daily()
    qc_last = qc.groupby("node").last()["reason"].to_dict() if len(qc) else {}
    alerts = store.alerts()
    active = alerts[alerts["closed"].isna()] if len(alerts) else alerts

    rows = []
    for d in devices:
        r = latest.loc[d.node] if d.node in latest.index else None
        stt = node_state(None if r is None else float(r["received"]), status.get(d.node), now)
        rows.append(
            {
                "durum": f"{STATE_DOT[stt]} {STATE_TEXT[stt]}",
                "düğüm": d.node,
                "ad": d.name,
                "zon": d.zone,
                "kaynak": "gerçek" if d.source == "real" else "sanal",
                "nem (VWC)": None if r is None else r["soil_vwc"],
                "sıcaklık °C": None if r is None else r["temp_c"],
                "pil V": None if r is None else r["battery_v"],
                "sinyal dBm": None if r is None else r["rssi"],
                "son veri": None
                if r is None
                else pd.Timestamp(int(r["received"]), unit="s", tz="UTC")
                .tz_convert(TZ)
                .strftime("%d %b %H:%M"),
                "günlük QC": QC_REASONS.get(qc_last.get(d.node, ""), "—"),
                "uyarı": int((active["node"] == d.node).sum()) if len(active) else 0,
                "_state": stt,
            }
        )
    table = pd.DataFrame(rows)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Çevrimiçi", f"{(table['_state'] == 'online').sum()} / {len(table)}")
    k2.metric("Etkin uyarı", f"{len(active)}")
    last_any = latest["received"].max() if len(latest) else None
    k3.metric("Son veri", "—" if last_any is None else f"{(now - last_any) / 60:.0f} dk önce")
    k4.metric("Ortalama pil", "—" if table["pil V"].isna().all() else f"{table['pil V'].mean():.2f} V")

    c_list, c_detail = st.columns([3, 2], gap="medium")
    with c_list:
        st.subheader("Düğümler")
        ev = st.dataframe(
            table.drop(columns="_state"),
            hide_index=True,
            width="stretch",
            on_select="rerun",
            selection_mode="single-row",
            key="dev_table",
            column_config={
                "nem (VWC)": st.column_config.ProgressColumn(
                    "nem (VWC)", min_value=0.0, max_value=0.45, format="%.3f"
                ),
                "pil V": st.column_config.NumberColumn(format="%.2f"),
            },
        )
        rows_sel = ev.selection.rows if ev and ev.selection else []
        if rows_sel:
            st.session_state["dev_sel"] = table.iloc[rows_sel[0]]["düğüm"]
        st.caption("Bir satıra tıklayın: sağda düğümün ayrıntısı ve son 48 saati görünür.")

        # konum haritası
        pts = []
        for d, r in zip(devices, rows):
            color = {
                "online": [46, 160, 67],
                "late": [240, 180, 0],
                "offline": [207, 34, 46],
                "never": [140, 140, 140],
            }
            pts.append(
                {
                    "pos": [d.lon, d.lat],
                    "color": color[r["_state"]] + [230],
                    "t0": f"{d.node} · {d.name}",
                    "t1": f"{r['durum']} · nem {r['nem (VWC)'] if r['nem (VWC)'] is not None else '—'}",
                }
            )
        st.pydeck_chart(
            pdk.Deck(
                layers=[
                    pdk.Layer(
                        "ScatterplotLayer",
                        data=pts,
                        get_position="pos",
                        get_fill_color="color",
                        get_radius=9,
                        radius_min_pixels=5,
                        stroked=True,
                        get_line_color=[255, 255, 255],
                        line_width_min_pixels=1.5,
                        pickable=True,
                    )
                ],
                initial_view_state=pdk.ViewState(
                    longitude=float(np.mean([d.lon for d in devices])),
                    latitude=float(np.mean([d.lat for d in devices])),
                    zoom=15.3,
                    pitch=35,
                ),
                map_provider="carto",
                map_style=pdk.map_styles.CARTO_LIGHT,
                tooltip={"html": "<b>{t0}</b><br/>{t1}"},
            ),
            height=330,
        )

    with c_detail:
        sel = st.session_state.get("dev_sel", devices[0].node)
        d = dev_by_node[sel]
        r = table.set_index("düğüm").loc[sel]
        st.subheader(f"{d.name}")
        st.markdown(
            f'<span class="tag">{r["durum"]}</span><span class="tag">{d.node}</span>'
            f'<span class="tag">{"gerçek" if d.source == "real" else "sanal"} · {d.firmware}</span>'
            f'<span class="tag">zon {d.zone}</span>',
            unsafe_allow_html=True,
        )
        hist = store.readings(sel, since=int(now - 48 * 3600))
        if hist.empty:
            st.info("Bu düğümden son 48 saatte ölçüm yok.")
        else:
            hist["t"] = pd.to_datetime(hist["ts"], unit="s", utc=True).dt.tz_convert(TZ)
            last = hist.iloc[-1]
            prev = hist[hist["ts"] <= last["ts"] - 3600]
            prev = prev.iloc[-1] if len(prev) else None
            m1, m2, m3 = st.columns(3)
            m1.metric(
                "Toprak nemi",
                f"{last['soil_vwc']:.3f}",
                None if prev is None else f"{last['soil_vwc'] - prev['soil_vwc']:+.3f} / 1 sa",
                help="Hacimsel su içeriği [m³/m³]; firmware ham değerden kalibrasyonsuz doğrusal ilişkiyle hesaplar.",
            )
            m2.metric("Sıcaklık", "—" if pd.isna(last["temp_c"]) else f"{last['temp_c']:.1f} °C")
            m3.metric("Hava nemi", "—" if pd.isna(last["hum_pct"]) else f"%{last['hum_pct']:.0f}")
            m4, m5, m6 = st.columns(3)
            m4.metric("Pil", "—" if pd.isna(last["battery_v"]) else f"{last['battery_v']:.2f} V")
            m5.metric("Sinyal", "—" if pd.isna(last["rssi"]) else f"{int(last['rssi'])} dBm")
            m6.metric("Hata", err_text(int(last["err"] or 0)))

            fig = make_subplots(
                rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.6, 0.4]
            )
            ok = hist[hist["live_qc"] == "ok"]
            fig.add_trace(
                go.Scatter(
                    x=ok["t"], y=ok["soil_vwc"], mode="lines", name="toprak nemi", line=dict(color="#0969da")
                ),
                row=1,
                col=1,
            )
            bad = hist[hist["live_qc"] != "ok"]
            if len(bad):
                fig.add_trace(
                    go.Scatter(
                        x=bad["t"],
                        y=bad["soil_vwc"],
                        mode="markers",
                        name="anlık kontrolden geçmedi",
                        marker=dict(color="#cf222e", size=7, symbol="x"),
                    ),
                    row=1,
                    col=1,
                )
            fig.add_trace(
                go.Scatter(
                    x=hist["t"], y=hist["temp_c"], mode="lines", name="sıcaklık", line=dict(color="#d4772c")
                ),
                row=2,
                col=1,
            )
            fig.update_yaxes(title_text="VWC", row=1, col=1)
            fig.update_yaxes(title_text="°C", row=2, col=1)
            fig.update_layout(
                height=360,
                margin=dict(l=10, r=10, t=10, b=10),
                legend=dict(orientation="h", y=1.08),
                hovermode="x",
            )
            st.plotly_chart(fig, width="stretch")
            src = "sanal (sim)" if bool(last["sim"]) else "gerçek ölçüm"
            st.caption(
                f"Kaynak: {src} · MQTT konusu `{topic_for(sel, 'telemetry')}` · {len(hist)} ölçüm / 48 saat"
            )
        qd = store.qc_daily(sel)
        if len(qd):
            qd = qd.tail(7).assign(karar=lambda x: x["reason"].map(lambda v: QC_REASONS.get(v, v)))
            st.markdown("**Günlük kalite kontrol** (gün kapanınca)")
            st.dataframe(
                qd[["day", "vwc_mean", "n", "karar"]].rename(
                    columns={"day": "gün", "vwc_mean": "ort. VWC", "n": "ölçüm"}
                ),
                hide_index=True,
                width="stretch",
            )

    st.subheader("Uyarılar")
    if len(active) == 0:
        st.success("Etkin uyarı yok.")
    else:
        a = active.copy()
        a["tür"] = a["kind"].map(lambda k: f"{ALERT_ICON.get(k, '•')} {k}")
        a["açıldı"] = (
            pd.to_datetime(a["opened"], unit="s", utc=True).dt.tz_convert(TZ).dt.strftime("%d %b %H:%M")
        )
        st.dataframe(a[["açıldı", "node", "tür", "message"]], hide_index=True, width="stretch")
    with st.expander("Kapanmış uyarılar"):
        closed = alerts[alerts["closed"].notna()] if len(alerts) else alerts
        if len(closed):
            c = closed.copy()
            for col in ("opened", "closed"):
                c[col] = (
                    pd.to_datetime(c[col], unit="s", utc=True).dt.tz_convert(TZ).dt.strftime("%d %b %H:%M")
                )
            st.dataframe(c[["opened", "closed", "node", "kind", "message"]], hide_index=True, width="stretch")
        else:
            st.write("Yok.")
    store.close()


dashboard()

with st.expander("Gerçek sensör nasıl bağlanır?"):
    st.markdown(
        """
1. `data/devices/registry.json` içinde düğümün satırında `source` alanını `"real"` yapın (konum ve zon aynı kalır)
   ya da yeni bir satır ekleyin. Simülatör o düğümü artık yayınlamaz.
2. Firmware `config.h` içinde `NODE_ID` aynı düğüm adı olsun; MQTT kullanıcısı `sulama` (ACL: yalnız telemetry/status
   yazar, cmd okur). Düğüm `sulama/<NODE_ID>/telemetry` konusuna aynı JSON'u yollar.
3. Alım servisi değişiklik gerektirmez; panel, QC ve ikiz gerçek veriyi aynı yoldan alır. Satırlarda `sim` bayrağı
   kaynağı ayırır.
4. Toprak sensörü kalibre edildiğinde (`tools/calibrate_sensor.py`) firmware'e `CALIB_SLOPE/INTERCEPT` girilir;
   config'teki `soil_raw_dry/wet` varsayımları ölçülen değerle değiştirilir.
"""
    )
