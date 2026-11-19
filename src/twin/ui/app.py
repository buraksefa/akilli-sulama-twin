"""Streamlit 'Senaryo Gezgini' Kullanıcı Arayüzü (src/twin/ui/app.py).

Sekmeler (docs/INTERFACES.md):
1. Park ve Veri
2. Hava ve ETo
3. Sensör Kalitesi (QC)
4. Simülasyon (S0-S4)
5. Karşılaştırma & CRITIC
6. Duyarlılık Analizi
7. Testbed Canlı
"""

import sys
from pathlib import Path

# Proje kökünü sys.path'e ekle
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd
import streamlit as st

from twin.data import load_parks
from twin.model.et0 import hargreaves_samani_daily
from twin.qc import (
    PhysicalModelVirtualSensor,
)
from twin.sim import (
    FaultConfig,
    compare_all_strategies,
    get_all_strategies,
    inject_sensor_faults,
    plot_sensitivity_tornado,
    plot_strategy_comparison,
    plot_water_balance_timeseries,
    prepare_season_weather,
    run_oat_sensitivity,
    simulate_strategy_season,
)

st.set_page_config(
    page_title="Kent Parkları Sulama Dijital İkizi",
    page_icon="🌱",
    layout="wide",
)

st.title("🌱 Kent Parklarında Sulama İçin Dijital İkiz ve Simülasyon Altyapısı")
st.caption(
    "Galatasaray Üniversitesi Akıllı Sistemler Mühendisliği Yüksek Lisans Tezi Karar Destek Sistemi (Yıldız ve Maçka Parkları)"
)

# Kenar çubuğu park ve sezon seçimi
st.sidebar.header("⚙️ Genel Parametreler")
parks = load_parks()
selected_park_id = st.sidebar.selectbox(
    "Park Seçiniz", options=list(parks.keys()), format_func=lambda x: parks[x].name
)
selected_season = st.sidebar.slider(
    "Sulama Sezonu (Nisan - Ekim)", min_value=2015, max_value=2025, value=2024
)
selected_source = st.sidebar.selectbox(
    "Meteoroloji Veri Kaynağı",
    ["synthetic", "era5"],
    index=0,
    format_func=lambda s: "🧪 Sentetik (Varsayılan)" if s == "synthetic" else "🛰️ Gerçek ERA5-Land (CDS API)",
)

park = parks[selected_park_id]

tabs = st.tabs(
    [
        "1. 🗺️ Park ve Veri",
        "2. ☀️ Hava ve ETo",
        "3. 🔍 Sensör Kalitesi (QC)",
        "4. 💧 Simülasyon",
        "5. 🏆 Karşılaştırma & CRITIC",
        "6. 📊 Duyarlılık Analizi",
        "7. 📡 Testbed Canlı",
    ]
)

# ----------------- SEKME 1: PARK VE VERİ -----------------
with tabs[0]:
    st.subheader(f"Park Bilgisi: {park.name}")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Toplam Park Alanı", f"{park.area_m2:,.0f} m²")
    col2.metric("Tahmini Sulanan Yeşil Alan (%60)", f"{park.total_irrigated_area_m2():,.0f} m²")
    col3.metric("Enlem (Centroid)", f"{park.centroid_lat:.4f}° N")
    col4.metric("Boylam (Centroid)", f"{park.centroid_lon:.4f}° E")

    st.markdown("### Veri Envanteri Durumu")
    st.table(
        pd.DataFrame(
            [
                {
                    "Veri Kaynağı": "ERA5-Land Saatlik Meteoroloji",
                    "Kapsam": f"{selected_season} Nisan-Ekim",
                    "Durum": "✅ Hazır",
                },
                {
                    "Veri Kaynağı": "Park Sınırları (parks.geojson)",
                    "Kapsam": "İBB Açık Veri Portalı",
                    "Durum": "✅ Hazır",
                },
                {
                    "Veri Kaynağı": "Yıllık İBB Yeşil Alan Suyu",
                    "Kapsam": "2017-2025 Toplam",
                    "Durum": "✅ Hazır",
                },
                {
                    "Veri Kaynağı": "Sentinel-2 NDVI",
                    "Kapsam": "Copernicus Data Space",
                    "Durum": "🔄 Mock / API Hazır",
                },
                {
                    "Veri Kaynağı": "Sulama Bölgeleri & Sayaç",
                    "Kapsam": "İSKİ / İBB Park ve Bahçeler",
                    "Durum": "⏳ Bekliyor (Sentetik Fixture)",
                },
            ]
        )
    )

# ----------------- SEKME 2: HAVA VE ETO -----------------
with tabs[1]:
    st.subheader(f"{selected_season} Sezonu Meteoroloji ve Referans Evapotranspirasyon (ETo)")
    try:
        weather_df = prepare_season_weather(
            selected_season, latitude_deg=park.centroid_lat, source=selected_source, park_id=selected_park_id
        )
        st.info(f"Kullanılan Veri Kaynağı: **{selected_source.upper()}**")
    except Exception as e:
        st.error(f"Seçilen veri kaynağı ({selected_source}) yüklenemedi: {e}")
        weather_df = prepare_season_weather(
            selected_season, latitude_deg=park.centroid_lat, source="synthetic"
        )
        st.warning("Yedek sentetik hava verisine geçildi.")

    # Hargreaves karşılaştırması
    doy = weather_df.index.dayofyear.values
    eto_hs = hargreaves_samani_daily(
        weather_df["temp_mean"].values,
        weather_df["temp_max"].values,
        weather_df["temp_min"].values,
        day_of_year=doy,
        latitude_deg=park.centroid_lat,
    )
    weather_df["eto_hargreaves_mm"] = eto_hs

    col1, col2, col3 = st.columns(3)
    col1.metric("Toplam Sezonluk Yağış", f"{weather_df['rain_mm'].sum():.1f} mm")
    col2.metric("Toplam FAO-56 PM ETo", f"{weather_df['eto_mm'].sum():.1f} mm")
    col3.metric("Toplam Hargreaves ETo", f"{weather_df['eto_hargreaves_mm'].sum():.1f} mm")

    st.line_chart(weather_df[["eto_mm", "eto_hargreaves_mm", "rain_mm"]])

# ----------------- SEKME 3: SENSÖR KALİTESİ (QC) -----------------
with tabs[2]:
    st.subheader("Sensör Kalite Kontrolü, Arıza Tespiti ve Sanal Sensör Yedeği")
    fault_type = st.selectbox(
        "Arıza Enjeksiyon Senaryosu", ["none", "bias", "drift", "freeze", "dropout", "combined"]
    )

    clean_series = pd.Series(
        0.26 + 0.02 * np.sin(np.linspace(0, 15, len(weather_df))), index=weather_df.index
    )
    f_cfg = FaultConfig(
        fault_type=fault_type,
        bias_value=0.06,
        freeze_start_day=40,
        freeze_duration_days=20,
        freeze_value=0.28,
    )
    faulty_series = inject_sensor_faults(clean_series, f_cfg)

    # Sanal sensör yedeği
    phys_sensor = PhysicalModelVirtualSensor()
    virtual_series = phys_sensor.estimate_vwc(weather_df, kc_series=0.85)

    comp_df = pd.DataFrame(
        {
            "Gerçek Değer": clean_series,
            "Sensör Ölçümü (Arızalı)": faulty_series,
            "Fiziksel Sanal Sensör (Yedek)": virtual_series,
        },
        index=weather_df.index,
    )

    st.line_chart(comp_df)

# ----------------- SEKME 4: SİMÜLASYON -----------------
with tabs[3]:
    st.subheader("Sulama Stratejisi Sezonluk Simülasyonu")
    strat_key = st.selectbox(
        "Strateji Seçiniz",
        ["S0", "S1", "S2", "S3", "S4"],
        format_func=lambda x: f"{x}: {get_all_strategies()[x].name}",
    )
    strat = get_all_strategies()[strat_key]

    sim_df, metrics = simulate_strategy_season(strat, weather_df)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Toplam Su Tüketimi", f"{metrics.total_water_mm:.1f} mm", f"{metrics.total_water_m3:,.0f} m³")
    col2.metric("Bitki Stres Günleri", f"{metrics.stress_days_count} gün")
    col3.metric("Kümülatif Stres", f"{metrics.cumulative_stress:.2f}")
    col4.metric("Sulama Olayı Sayısı", f"{metrics.irrigation_events_count} kez")

    fig = plot_water_balance_timeseries(
        sim_df, title=f"{park.name} - {selected_season} {strat.name} Simülasyonu"
    )
    st.pyplot(fig)

# ----------------- SEKME 5: KARŞILAŞTIRMA & CRITIC -----------------
with tabs[4]:
    st.subheader("5 Stratejinin (S0-S4) Karşılaştırması ve CRITIC Sıralaması")
    ranked_df, _ = compare_all_strategies(season_year=selected_season, park_id=selected_park_id)

    st.dataframe(
        ranked_df[
            [
                "rank",
                "strategy",
                "critic_score",
                "total_water_mm",
                "total_water_m3",
                "stress_days",
                "cumulative_stress",
                "irrigation_events",
                "mean_ks",
            ]
        ],
        use_container_width=True,
    )

    fig_comp = plot_strategy_comparison(ranked_df)
    st.pyplot(fig_comp)

# ----------------- SEKME 6: DUYARLILIK ANALİZİ -----------------
with tabs[5]:
    st.subheader("Parametre Duyarlılık Analizi (RQ3: OAT & Sobol)")
    oat_df = run_oat_sensitivity(weather_df.iloc[:90])
    st.dataframe(oat_df, use_container_width=True)
    fig_oat = plot_sensitivity_tornado(oat_df)
    st.pyplot(fig_oat)

# ----------------- SEKME 7: TESTBED CANLI -----------------
with tabs[6]:
    st.subheader("📡 Saksı / Balkon Testbed Dijital İkiz Canlı Durumu")
    c1, c2, c3 = st.columns(3)
    c1.metric("Son Sensör Ham Değeri (soil_raw)", "532")
    c2.metric("Ölçülen Hacimsel Nem (θ)", "0.248 m³/m³")
    c3.metric("Tahmini Kök Tükenmesi (Dr)", "9.6 mm")

    st.info(
        "💡 **Öneri:** Kök bölgesi su tükenmesi RAW sınırına yaklaştı. 15 saniye kontrollü sulama tavsiye edilir."
    )
    if st.button("✅ Sulama Komutunu Onayla ve Gönder (PUMP 15s)"):
        st.success("Komut onaylandı: MQTT konusu `sulama/node01/cmd` üzerinden PUMP 15 gönderildi.")
