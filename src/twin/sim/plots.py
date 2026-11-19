"""Tez kalitesinde grafik üretim ve dışa aktarma modülü (Matplotlib, Türkçe etiketli).

Üretilen grafikler:
1. Toprak nemi ve su dengesi zaman serisi (Nem, RAW, TAW, Yağış, Sulama)
2. Strateji karşılaştırma grafiği (Su tüketimi vs. Stres günleri)
3. CRITIC ağırlıkları ve sıralama grafiği
4. Parametre duyarlılık grafiği (OAT Tornado / Elastikiyet)
5. Arıza enjeksiyonu ve arıza toleransı grafiği (RQ1)
"""

from pathlib import Path
from typing import Optional

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

matplotlib.use("Agg")  # Başsız (headless) render modu


def setup_plot_style():
    """Grafik stil ve tipografi ayarları."""
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial", "Helvetica"]
    plt.rcParams["axes.edgecolor"] = "#cccccc"
    plt.rcParams["axes.linewidth"] = 0.8
    plt.rcParams["grid.color"] = "#eeeeee"
    plt.rcParams["grid.linestyle"] = "--"


def plot_water_balance_timeseries(
    sim_df: pd.DataFrame,
    title: str = "Toprak Su Dengesi ve Sulama Dinamiği",
    output_path: Optional[Path | str] = None,
) -> plt.Figure:
    """Toprak nemi, RAW, TAW, yağış ve sulama olaylarını çizer."""
    setup_plot_style()
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]}
    )

    # 1. Panel: Hacimsel Toprak Nemi (VWC)
    theta = sim_df["theta_vwc"]
    raw_mm = sim_df["raw_mm"].iloc[0]

    # Eşik çizgileri
    theta_fc = theta.max()
    theta_crit = theta_fc - (raw_mm / (1000.0 * 0.30))  # critical theta

    ax1.plot(sim_df.index, theta, label="Toprak Nemi (θ)", color="#1b7837", lw=1.8)
    ax1.axhline(theta_fc, color="#2166ac", ls="--", alpha=0.7, label="Tarla Kapasitesi (θ_FC)")
    ax1.axhline(theta_crit, color="#b2182b", ls=":", alpha=0.8, label="Kritik Nem Eşiği (θ_crit)")

    ax1.set_ylabel("Hacimsel Su İçeriği θ [m³/m³]", fontsize=10)
    ax1.set_title(title, fontsize=12, pad=10, fontweight="bold")
    ax1.grid(True)
    ax1.legend(loc="upper right", framealpha=0.9, fontsize=9)

    # 2. Panel: Yağış ve Sulama
    ax2.bar(sim_df.index, sim_df["rain_mm"], width=0.8, label="Yağış [mm]", color="#4393c3", alpha=0.8)
    ax2.bar(
        sim_df.index,
        sim_df["irrigation_gross_mm"],
        width=0.8,
        bottom=sim_df["rain_mm"],
        label="Sulama [mm]",
        color="#d6604d",
        alpha=0.8,
    )

    ax2.set_ylabel("Su Girişi [mm]", fontsize=10)
    ax2.set_xlabel("Tarih", fontsize=10)
    ax2.grid(True)
    ax2.legend(loc="upper right", framealpha=0.9, fontsize=9)

    plt.tight_layout()
    if output_path:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(p, dpi=300)
    return fig


def plot_strategy_comparison(
    ranked_metrics_df: pd.DataFrame,
    output_path: Optional[Path | str] = None,
) -> plt.Figure:
    """Stratejilerin su kullanımı ve stres günlerini karşılaştıran çift eksenli çubuk grafik."""
    setup_plot_style()
    fig, ax1 = plt.subplots(figsize=(10, 5))

    strategies = ranked_metrics_df["strategy"]
    x = np.arange(len(strategies))
    width = 0.35

    color1 = "#2b83ba"
    color2 = "#d7191c"

    ax1.bar(x - width / 2, ranked_metrics_df["total_water_mm"], width, label="Toplam Su [mm]", color=color1)
    ax1.set_ylabel("Toplam Sulama Suyu [mm]", color=color1, fontsize=11, fontweight="bold")
    ax1.tick_params(axis="y", labelcolor=color1)

    ax2 = ax1.twinx()
    ax2.bar(x + width / 2, ranked_metrics_df["stress_days"], width, label="Stresli Gün Sayısı", color=color2)
    ax2.set_ylabel("Bitki Stres Günleri (Ks < 1.0)", color=color2, fontsize=11, fontweight="bold")
    ax2.tick_params(axis="y", labelcolor=color2)

    ax1.set_xticks(x)
    ax1.set_xticklabels(strategies, fontsize=10)
    ax1.set_title(
        "Sulama Stratejileri Su Tüketimi ve Bitki Stresi Karşılaştırması",
        fontsize=12,
        fontweight="bold",
        pad=12,
    )
    ax1.grid(True, axis="y")

    plt.tight_layout()
    if output_path:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(p, dpi=300)
    return fig


def plot_sensitivity_tornado(
    oat_df: pd.DataFrame,
    output_path: Optional[Path | str] = None,
) -> plt.Figure:
    """OAT duyarlılık analizi tornado etki grafiği."""
    setup_plot_style()
    fig, ax = plt.subplots(figsize=(9, 5))

    params = oat_df["parameter"].unique()
    y_pos = np.arange(len(params))

    # +%20 ve -%20 etki farkı
    low_impacts = []
    high_impacts = []

    for p in params:
        sub = oat_df[oat_df["parameter"] == p]
        low = sub[sub["factor"] == 0.8]["water_change_pct"].values
        high = sub[sub["factor"] == 1.2]["water_change_pct"].values
        low_impacts.append(low[0] if len(low) > 0 else 0.0)
        high_impacts.append(high[0] if len(high) > 0 else 0.0)

    ax.barh(y_pos, high_impacts, height=0.4, color="#1b7837", alpha=0.8, label="+%20 Parametre Değişimi")
    ax.barh(y_pos, low_impacts, height=0.4, color="#b2182b", alpha=0.8, label="-%20 Parametre Değişimi")

    ax.axvline(0, color="black", lw=0.8)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(params, fontsize=10)
    ax.set_xlabel("Su Tüketimindeki Yüzdesel Değişim (%)", fontsize=10)
    ax.set_title(
        "OAT Parametre Duyarlılık Analizi (Su Tüketimi Etkisi)", fontsize=12, fontweight="bold", pad=12
    )
    ax.grid(True, axis="x")
    ax.legend(loc="lower right")

    plt.tight_layout()
    if output_path:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(p, dpi=300)
    return fig
