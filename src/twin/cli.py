"""Typer tabanlı komut satırı arayüzü (CLI).

Sözleşme: docs/INTERFACES.md.
Komutlar:
- twin fetch-era5
- twin qc
- twin simulate
- twin compare
- twin sensitivity
- twin export-figures
"""

from pathlib import Path
from typing import List, Optional

import pandas as pd
import typer

from twin.data.era5 import (
    build_era5_processed_dataset,
    generate_synthetic_era5,
)
from twin.data.era5_download import (
    check_cdsapirc,
    check_park_grid_overlap,
    download_era5_range,
)
from twin.qc import find_gaps, find_restarts, load_sensor_csv, run_rule_based_qc
from twin.sim import (
    compare_all_strategies,
    get_all_strategies,
    plot_sensitivity_tornado,
    plot_strategy_comparison,
    plot_water_balance_timeseries,
    prepare_season_weather,
    run_oat_sensitivity,
    run_sobol_morris_sampling,
    simulate_strategy_season,
)

app = typer.Typer(help="Galatasaray Üniversitesi Kent Parkları Sulama Dijital İkizi CLI Aracı")
era5_app = typer.Typer(help="ERA5-Land reanaliz verisi indirme ve işleme komutları")
app.add_typer(era5_app, name="era5")

from twin.devices.cli import app as devices_app  # noqa: E402

app.add_typer(devices_app, name="devices")


def _parse_int_range(range_str: str) -> List[int]:
    """'2015-2025' veya '4-10' veya '2024' veya '4,5,6' biçimindeki aralıkları listeye çevirir."""
    range_str = range_str.strip()
    if "-" in range_str:
        parts = range_str.split("-")
        start, end = int(parts[0].strip()), int(parts[1].strip())
        return list(range(start, end + 1))
    if "," in range_str:
        return [int(x.strip()) for x in range_str.split(",") if x.strip()]
    return [int(range_str)]


@era5_app.command("download")
def era5_download_cmd(
    park: str = typer.Option("yildiz", "--park", help="Park ID (yildiz / macka)"),
    years: str = typer.Option("2015-2025", "--years", help="Yıllar aralığı (örn: 2015-2025 veya 2024)"),
    months: str = typer.Option("4-10", "--months", help="Aylar aralığı (örn: 4-10 veya 4,5,6)"),
    out: str = typer.Option("data/raw/era5", "--out", help="Ham NetCDF kayıt dizini"),
):
    """Copernicus CDS API üzerinden ERA5-Land saatlik NetCDF verilerini indirir."""
    try:
        check_cdsapirc()
    except Exception as e:
        typer.secho(f"❌ CDS API Kimlik Doğrulama Hatası:\n{e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    parsed_years = _parse_int_range(years)
    parsed_months = _parse_int_range(months)

    typer.echo(f"ERA5-Land İndirme Başlatılıyor: Park={park}, Yıllar={parsed_years}, Aylar={parsed_months}")
    check_park_grid_overlap()

    try:
        downloaded = download_era5_range(
            years=parsed_years,
            months=parsed_months,
            park_id=park,
            out_dir=out,
        )
        typer.secho(
            f"✅ İndirme tamamlandı: {len(downloaded)} dosya kontrol edildi/indirildi ({out}).",
            fg=typer.colors.GREEN,
        )
    except Exception as e:
        typer.secho(f"❌ İndirme sırasında hata oluştu: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


@era5_app.command("build")
def era5_build_cmd(
    raw_dir: str = typer.Option("data/raw/era5", "--raw-dir", help="Ham NetCDF dizini"),
    out_dir: str = typer.Option("data/processed", "--out-dir", help="İşlenmiş CSV dizini"),
    years: Optional[str] = typer.Option(None, "--years", help="Filtrelenecek yıllar (örn: 2015-2025)"),
    parks: str = typer.Option("yildiz,macka", "--parks", help="İşlenecek parklar (virgülle ayrılmış)"),
):
    """Ham ERA5-Land NetCDF dosyalarını işler, FAO-56 ETo hesaplar ve CSV formatına dönüştürür."""
    parsed_years = _parse_int_range(years) if years else None
    target_parks = [p.strip() for p in parks.split(",") if p.strip()]

    typer.echo(f"ERA5 Veri Seti Derleniyor: Ham Dizin={raw_dir} -> Çıktı={out_dir}, Parklar={target_parks}")
    results = build_era5_processed_dataset(
        raw_dir=raw_dir,
        processed_dir=out_dir,
        years=parsed_years,
        park_ids=target_parks,
    )

    if not results:
        typer.secho(
            f"⚠️ {raw_dir} altında işlenecek NetCDF dosyası bulunamadı. Önce 'twin era5 download' çalıştırın.",
            fg=typer.colors.YELLOW,
        )
        return

    typer.secho(
        f"✅ Toplam {len(results)} park-sezon veri seti başarıyla derlendi ve kaydedildi ({out_dir}).",
        fg=typer.colors.GREEN,
    )


@app.command("fetch-era5")
def fetch_era5(
    start: str = typer.Option("2024-04-01", "--start", help="Başlangıç tarihi (YYYY-MM-DD veya YYYY-MM)"),
    end: str = typer.Option("2024-10-31", "--end", help="Bitiş tarihi (YYYY-MM-DD veya YYYY-MM)"),
    park: str = typer.Option("yildiz", "--park", help="Park ID (yildiz veya macka)"),
    out: Optional[str] = typer.Option(None, "--out", help="Çıktı CSV dosya yolu"),
):
    """ERA5-Land saatlik meteoroloji verisini indirir veya sentetik üretir."""
    typer.echo(f"ERA5 verisi hazırlanıyor: Park={park}, Aralık={start} -> {end}")
    df = generate_synthetic_era5(start_date=start, end_date=end, seed=42)
    out_path = Path(out) if out else Path("data/raw") / f"era5_{park}_{start[:7]}_{end[:7]}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path)
    typer.echo(f"✅ Veri başarıyla kaydedildi: {out_path} ({len(df)} kayıt)")


@app.command("qc")
def qc(
    csv_path: str = typer.Argument(..., help="Kontrol edilecek telemetri CSV dosya yolu"),
    interval: float = typer.Option(60.0, "--interval", help="Beklenen ölçüm aralığı (sn)"),
    flags_out: Optional[str] = typer.Option(None, "--flags-out", help="Bayrakların yazılacağı CSV dosyası"),
):
    """Sensör zaman serisi için kalite kontrol ve arıza raporu üretir."""
    typer.echo(f"Kalite kontrolü yürütülüyor: {csv_path}")
    df = load_sensor_csv(csv_path)
    gaps = find_gaps(df, interval)
    restarts = find_restarts(df)
    flags = run_rule_based_qc(df, interval)

    typer.echo(f"Toplam kayıt: {len(df)}")
    typer.echo(f"Boşluk sayısı (> {1.5 * interval:.0f}s): {len(gaps)}")
    typer.echo(f"Yeniden başlatma sayısı: {len(restarts)}")

    if flags_out:
        out_df = pd.DataFrame(flags, index=df.index)
        out_df.to_csv(flags_out)
        typer.echo(f"✅ Bayraklar kaydedildi: {flags_out}")


@app.command("simulate")
def simulate(
    park: str = typer.Option("yildiz", "--park", help="Park ID (yildiz / macka)"),
    season: int = typer.Option(2024, "--season", help="Sulama sezonu yılı (2015-2025)"),
    strategy: str = typer.Option("S4", "--strategy", help="Strateji (S0, S1, S2, S3, S4)"),
    source: str = typer.Option("auto", "--source", help="Veri kaynağı (auto / era5 / synthetic)"),
    out: Optional[str] = typer.Option(None, "--out", help="Çıktı CSV yolu"),
):
    """Belirtilen park ve sezon için sulama stratejisi simülasyonunu koşturur."""
    strats = get_all_strategies()
    if strategy not in strats:
        typer.echo(f"❌ Geçersiz strateji: {strategy}. Seçenekler: {list(strats.keys())}")
        raise typer.Exit(code=1)

    typer.echo(f"Simülasyon başlatılıyor: Park={park}, Sezon={season}, Strateji={strategy}, Kaynak={source}")
    try:
        weather = prepare_season_weather(season_year=season, source=source, park_id=park)
    except Exception as e:
        typer.secho(f"❌ Hava verisi hazırlama hatası: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Hava verisi kaynağı: {weather.attrs.get('source', 'unknown')}")
    sim_df, metrics = simulate_strategy_season(strats[strategy], weather)

    typer.echo(f"--- Sonuçlar ({strategy}) ---")
    typer.echo(f"Toplam Sulama: {metrics.total_water_mm:.1f} mm ({metrics.total_water_m3:,.0f} m³)")
    typer.echo(
        f"Stres Günleri: {metrics.stress_days_count} gün (Kümülatif Stres: {metrics.cumulative_stress:.2f})"
    )
    typer.echo(f"Sulama Olayı: {metrics.irrigation_events_count} kez")

    if out:
        sim_df.to_csv(out)
        typer.echo(f"✅ Simülasyon zaman serisi kaydedildi: {out}")


@app.command("efficiency")
def efficiency(
    park: str = typer.Option("yildiz", "--park", help="Park ID"),
    years: str = typer.Option("2020-2024", "--years", help="Sezon yılları, ör. 2020-2024 veya 2021,2023"),
    source: str = typer.Option("auto", "--source", help="Veri kaynağı (auto / era5 / synthetic)"),
    out_dir: str = typer.Option("outputs/efficiency", "--out", help="CSV çıktı dizini"),
    vegetation: Optional[str] = typer.Option(
        None, "--vegetation", help="Bitki profili (ör. turf_cool_season); boşsa varsayılan config"
    ),
):
    """Stratejileri kâhin alt sınırına (stressiz en az su) göre karşılaştırır."""
    from twin.config import config_for_vegetation
    from twin.data.parks import load_parks
    from twin.sim.efficiency import allowed_depletion_sweep, park_zone_requirement, season_efficiency_table

    cfg = config_for_vegetation(vegetation) if vegetation else None
    tag = f"{park}_{vegetation}" if vegetation else park
    parks = load_parks()
    zones = parks[park].zones if park in parks else []

    if "-" in years:
        y0, y1 = (int(v) for v in years.split("-"))
        year_list = list(range(y0, y1 + 1))
    else:
        year_list = [int(v) for v in years.split(",")]

    tables, sweeps, zone_tables = [], [], []
    for year in year_list:
        weather = prepare_season_weather(season_year=year, source=source, park_id=park)
        typer.echo(f"Sezon {year}: hava verisi kaynağı = {weather.attrs.get('source', 'unknown')}")
        t = season_efficiency_table(weather, config=cfg)
        t.insert(0, "season", year)
        tables.append(t)
        s = allowed_depletion_sweep(weather, config=cfg)
        s.insert(0, "season", year)
        sweeps.append(s)
        zt = park_zone_requirement(weather, zones)
        zt.insert(0, "season", year)
        zone_tables.append(zt)

    table = pd.concat(tables, ignore_index=True)
    sweep = pd.concat(sweeps, ignore_index=True)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_path / f"efficiency_{tag}.csv", index=False)
    sweep.to_csv(out_path / f"allowed_depletion_sweep_{tag}.csv", index=False)
    if zone_tables:
        pd.concat(zone_tables, ignore_index=True).to_csv(out_path / f"zones_{park}.csv", index=False)

    cols = [
        "season",
        "strategy",
        "irrigation_gross_mm",
        "excess_vs_oracle_mm",
        "saving_vs_s0_pct",
        "stress_days",
    ]
    typer.echo(table[cols].round(1).to_string(index=False))
    typer.echo(f"✅ Kaydedildi: {out_path}")


@app.command("learned-policy")
def learned_policy(
    park: str = typer.Option("yildiz", "--park", help="Park ID"),
    years: str = typer.Option("2020-2024", "--years", help="Sezon yılları, ör. 2020-2024"),
    margins: str = typer.Option("1.0", "--margins", help="Hedef D/RAW oranları, ör. 1.0,0.9,0.8"),
    iterations: int = typer.Option(3, "--iterations", help="DAgger tur sayısı"),
    seed: int = typer.Option(0, "--seed", help="Model rastgele tohumu"),
    source: str = typer.Option("auto", "--source", help="Veri kaynağı (auto / era5 / synthetic)"),
    out_dir: str = typer.Option("outputs/learned_policy", "--out", help="CSV çıktı dizini"),
):
    """S5 (kalıcılık JIT) ve S6 (DAgger ile öğrenilmiş) politikaları yıl-dışı-bırak ile değerlendirir."""
    import time

    from twin.sim.learned_policy import leave_one_year_out

    y0, y1 = (int(v) for v in years.split("-"))
    seasons = {}
    for y in range(y0, y1 + 1):
        seasons[y] = prepare_season_weather(season_year=y, source=source, park_id=park)
        typer.echo(f"Sezon {y}: hava verisi kaynağı = {seasons[y].attrs.get('source', 'unknown')}")

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    tables = []
    for f in (float(v) for v in margins.split(",")):
        t0 = time.perf_counter()
        tables.append(leave_one_year_out(seasons, iterations=iterations, seed=seed, target_fraction_of_raw=f))
        typer.echo(f"D = {f}·RAW: {time.perf_counter() - t0:.1f} s")
    table = pd.concat(tables, ignore_index=True)
    table.to_csv(out_path / f"loyo_{park}.csv", index=False)
    cols = ["target_fraction_of_raw", "season", "strategy", "irrigation_gross_mm", "excess_vs_oracle_mm"]
    cols += ["stress_days", "cumulative_stress", "relative_et_deficit"]
    sel = table[table["strategy"].isin(["ORACLE", "S2", "S4", "S5", "S6"])]
    typer.echo(sel[cols].round(3).to_string(index=False))
    typer.echo(f"✅ Kaydedildi: {out_path}")


@app.command("noisy-state")
def noisy_state(
    park: str = typer.Option("yildiz", "--park", help="Park ID"),
    years: str = typer.Option("2020-2024", "--years", help="Sezon yılları, ör. 2020-2024"),
    seeds: int = typer.Option(10, "--seeds", help="Tohum sayısı (0..n-1)"),
    source: str = typer.Option("auto", "--source", help="Veri kaynağı (auto / era5 / synthetic)"),
    out_dir: str = typer.Option("outputs/noisy_state", "--out", help="CSV çıktı dizini"),
):
    """S5'i durum kestiricisi (true/sensor/openloop/enkf) × ETo yanlılığı × güvenlik payı ile koşturur."""
    import time

    from twin.sim.learned_policy import noisy_state_experiment

    y0, y1 = (int(v) for v in years.split("-"))
    seasons = {}
    for y in range(y0, y1 + 1):
        seasons[y] = prepare_season_weather(season_year=y, source=source, park_id=park)
        typer.echo(f"Sezon {y}: hava verisi kaynağı = {seasons[y].attrs.get('source', 'unknown')}")

    t0 = time.perf_counter()
    table = noisy_state_experiment(seasons, seeds=tuple(range(seeds)))
    typer.echo(f"Süre: {time.perf_counter() - t0:.1f} s, {len(table)} sezon koşusu")

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_path / f"noisy_state_{park}.csv", index=False)
    typer.echo(f"✅ Kaydedildi: {out_path / f'noisy_state_{park}.csv'}")


@app.command("forecast-skill")
def forecast_skill(
    year: int = typer.Option(2024, "--year", help="Sezon (önceki-koşu arşivi 2024'ten itibaren var)"),
    seeds: int = typer.Option(10, "--seeds", help="Sensör gürültüsü tohum sayısı"),
    lead: int = typer.Option(1, "--lead", help="Kararda kullanılan tahmin vadesi (gün)"),
    out_dir: str = typer.Option("outputs/forecast_skill", "--out", help="CSV çıktı dizini"),
):
    """Open-Meteo tahmin isabeti (ERA5'e göre) ve tahmine dayalı kararın sanal parktaki değeri."""
    import time

    from twin.config import TwinConfig
    from twin.data.forecast import fetch_previous_runs_daily
    from twin.sim.forecast_skill import decision_value, skill_table
    from twin.sim.virtual_world import build_world, load_world_spec

    cache = Path(f"data/external/open_meteo_previous_runs_yildiz_{year}.csv")
    if cache.is_file():
        fc = pd.read_csv(cache, index_col=0, parse_dates=True)
        typer.echo(f"Tahmin arşivi: {cache}")
    else:
        era5 = TwinConfig().era5
        fc = fetch_previous_runs_daily(
            float(era5.yildiz_lat.value), float(era5.yildiz_lon.value), f"{year}-04-01", f"{year}-10-31"
        )
        fc["source"] = "open_meteo_previous_runs"
        cache.parent.mkdir(parents=True, exist_ok=True)
        fc.to_csv(cache)
        typer.echo(f"Tahmin arşivi indirildi: {cache}")
    weather = prepare_season_weather(season_year=year, source="era5", park_id="yildiz")
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    skill = skill_table(fc, weather)
    skill["referans"] = weather.attrs.get("source")
    skill.to_csv(out_path / f"skill_yildiz_{year}.csv", index=False)
    t0 = time.perf_counter()
    world = build_world(load_world_spec("data/scenarios/yildiz_dunya.json"), "data/public/parks.geojson")
    dv = decision_value(world, weather, fc, lead=lead, seeds=range(seeds))
    dv.to_csv(out_path / f"decision_value_yildiz_{year}.csv", index=False)
    typer.echo(f"Karar değeri koşusu: {time.perf_counter() - t0:.1f} s")
    typer.echo(
        skill[["tahmin", "eto_mae_mm", "eto_bias_mm", "yagis_mae_mm", "pod_1mm", "far_1mm"]]
        .round(3)
        .to_string(index=False)
    )
    g = dv.groupby(["strateji", "bilgi"])[["su_m3", "stresli_alan_ort_pct", "derin_sizma_m3"]].mean().round(1)
    typer.echo(g.to_string())
    typer.echo(f"✅ Kaydedildi: {out_path}")


@app.command("heterogeneity")
def heterogeneity(
    years: str = typer.Option("2024", "--years", help="Virgülle ayrılmış sezonlar (ör. 2020,2022,2024)"),
    seeds: int = typer.Option(10, "--seeds", help="Sensör gürültüsü/arıza tohum sayısı"),
    out_dir: str = typer.Option("outputs/heterogeneity", "--out", help="CSV çıktı dizini"),
    no_faults: bool = typer.Option(False, "--no-faults", help="Sensör arızalarını kapat (yalnız gürültü)"),
    with_qc: bool = typer.Option(False, "--with-qc", help="Sensörlü ikizleri QC'li ve QC'siz koş"),
    no_drift_test: bool = typer.Option(
        False, "--no-drift-test", help="QC'de model-sensör tutarlılık (kayma) testini kapat"
    ),
):
    """Zon içi farklılık: güvenlik payı × sensör yerleşimi × zon boyutu (sanal Yıldız dünyası, ERA5 hava)."""
    import time

    from twin.sim.heterogeneity import heterogeneity_experiment, summarize_experiment
    from twin.sim.virtual_world import load_world_spec

    spec = load_world_spec("data/scenarios/yildiz_dunya.json")
    if no_faults:
        spec["sensors"]["fault_probabilities"] = {k: 0.0 for k in spec["sensors"]["fault_probabilities"]}
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    for year in [int(y) for y in years.split(",")]:
        weather = prepare_season_weather(season_year=year, source="era5", park_id="yildiz")
        t0 = time.perf_counter()
        df = heterogeneity_experiment(
            spec,
            "data/public/parks.geojson",
            weather,
            seeds=range(seeds),
            qc_options=(False, True) if with_qc else (False,),
            qc_drift=not no_drift_test,
        )
        df.insert(0, "yil", year)
        df.insert(1, "sensor_arizasi", not no_faults)
        summ = summarize_experiment(df)
        summ.insert(0, "yil", year)
        summ.insert(1, "sensor_arizasi", not no_faults)
        df.to_csv(out_path / f"heterogeneity_runs_yildiz_{year}.csv", index=False)
        summ.to_csv(out_path / f"heterogeneity_summary_yildiz_{year}.csv", index=False)
        typer.echo(
            f"{year}: {len(df)} koşu, {time.perf_counter() - t0:.1f} s, kaynak {weather.attrs.get('source')}"
        )
        cols = [
            "zon_duzeni",
            "zon_sayisi",
            "sensor_sayisi",
            "yerlesim",
            "strateji",
            "qc",
            "pay",
            "su_m3",
            "su_kahine_orani",
            "stresli_alan_ort_pct",
            "stresli_alan_maks_pct",
        ]
        typer.echo(summ[cols].round(3).to_string(index=False))
    typer.echo(f"✅ Kaydedildi: {out_path}")


@app.command("qc-detection")
def qc_detection_cmd(
    years: str = typer.Option("2024", "--years", help="Virgülle ayrılmış sezonlar"),
    seeds: int = typer.Option(10, "--seeds", help="Sensör tohum sayısı"),
    out_dir: str = typer.Option("outputs/sensor_qc", "--out", help="CSV çıktı dizini"),
    no_drift_test: bool = typer.Option(
        False, "--no-drift-test", help="Model-sensör tutarlılık (kayma) testini kapat"
    ),
    drift_slope_max: Optional[float] = typer.Option(
        None, "--drift-slope-max", help="Kayma eşiğini geçersiz kıl (kalibrasyon için ör. inf)"
    ),
):
    """Çevrimiçi sensör QC'sinin arıza yakalama başarısı ve gecikmesi (sanal Yıldız dünyası, ERA5 hava)."""
    import time

    from twin.config import TwinConfig
    from twin.sim.heterogeneity import qc_detection
    from twin.sim.virtual_world import load_world_spec

    spec = load_world_spec("data/scenarios/yildiz_dunya.json")
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    for year in [int(y) for y in years.split(",")]:
        weather = prepare_season_weather(season_year=year, source="era5", park_id="yildiz")
        t0 = time.perf_counter()
        cfg = TwinConfig()
        if drift_slope_max is not None:
            cfg.sensor_qc.drift_slope_max.value = float(drift_slope_max)
        df = qc_detection(
            spec,
            "data/public/parks.geojson",
            weather,
            seeds=range(seeds),
            config=cfg,
            qc_drift=not no_drift_test,
        )
        df.insert(0, "yil", year)
        df["kaynak"] = f"synthetic_world+{weather.attrs.get('source')}"
        df.to_csv(out_path / f"detection_{year}.csv", index=False)
        df["gecikme"] = df["ilk_ret_gunu"] - df["ariza_baslangic_gunu"]
        g = df.groupby("ariza").agg(
            n=("ariza", "size"), yakalanan=("yakalandi", "mean"), gecikme_ortanca=("gecikme", "median")
        )
        typer.echo(f"{year}: {len(df)} sensör-sezon, {time.perf_counter() - t0:.1f} s")
        typer.echo(g.round(3).to_string())
    typer.echo(f"✅ Kaydedildi: {out_path}")


@app.command("compare")
def compare(
    park: str = typer.Option("yildiz", "--park", help="Park ID"),
    season: int = typer.Option(2024, "--season", help="Sulama sezonu yılı"),
    source: str = typer.Option("auto", "--source", help="Veri kaynağı (auto / era5 / synthetic)"),
    out: Optional[str] = typer.Option(None, "--out", help="CRITIC sıralama CSV çıktısı"),
):
    """5 sulama stratejisini (S0-S4) koşturur ve CRITIC ile sıralar."""
    typer.echo(f"Tüm stratejiler karşılaştırılıyor: Park={park}, Sezon={season}, Kaynak={source}")
    try:
        ranked_df, _ = compare_all_strategies(season_year=season, park_id=park, source=source)
    except Exception as e:
        typer.secho(f"❌ Karşılaştırma hatası: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Hava verisi kaynağı: {ranked_df.attrs.get('weather_source', 'unknown')}")
    typer.echo("\n--- CRITIC Strateji Sıralaması ---")
    typer.echo(
        ranked_df[["rank", "strategy", "critic_score", "total_water_mm", "stress_days"]].to_string(
            index=False
        )
    )

    if out:
        ranked_df.to_csv(out, index=False)
        typer.echo(f"\n✅ Sıralama tablosu kaydedildi: {out}")


@app.command("sensitivity")
def sensitivity(
    park: str = typer.Option("yildiz", "--park", help="Park ID"),
    season: int = typer.Option(2024, "--season", help="Sulama sezonu yılı"),
    method: str = typer.Option("oat", "--method", help="Yöntem: 'oat' veya 'sobol'"),
    source: str = typer.Option("auto", "--source", help="Veri kaynağı (auto / era5 / synthetic)"),
    out: Optional[str] = typer.Option(None, "--out", help="Duyarlılık CSV çıktısı"),
):
    """Parametre duyarlılık analizini (OAT veya Sobol) koşturur."""
    typer.echo(f"Duyarlılık analizi yürütülüyor: Yöntem={method.upper()}, Kaynak={source}")
    try:
        weather = prepare_season_weather(season_year=season, source=source, park_id=park).iloc[:90]
    except Exception as e:
        typer.secho(f"❌ Duyarlılık analizi hatası: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Hava verisi kaynağı: {weather.attrs.get('source', 'unknown')}")
    if method.lower() == "oat":
        res_df = run_oat_sensitivity(weather)
    else:
        res_df = run_sobol_morris_sampling(weather, num_samples=30)

    typer.echo(res_df.head(10).to_string(index=False))
    if out:
        res_df.to_csv(out, index=False)
        typer.echo(f"✅ Sonuçlar kaydedildi: {out}")


@app.command("export-figures")
def export_figures(
    out_dir: str = typer.Option("outputs/figures", "--out", help="Grafiklerin kaydedileceği dizin"),
    season: int = typer.Option(2024, "--season", help="Kullanılacak sezon yılı"),
):
    """Tez için gerekli tüm yayın kalitesinde grafikleri üretir ve kaydeder."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    typer.echo(f"Grafikler üretiliyor -> {out_path}")

    weather = prepare_season_weather(season_year=season)
    strats = get_all_strategies()

    # 1. Su dengesi grafiği
    sim_df, _ = simulate_strategy_season(strats["S4"], weather)
    plot_water_balance_timeseries(sim_df, output_path=out_path / "water_balance_s4.png")

    # 2. Karşılaştırma grafiği
    ranked_df, _ = compare_all_strategies(season_year=season, park_id="yildiz")
    plot_strategy_comparison(ranked_df, output_path=out_path / "strategy_comparison.png")

    # 3. OAT Tornado grafiği
    oat_df = run_oat_sensitivity(weather.iloc[:90])
    plot_sensitivity_tornado(oat_df, output_path=out_path / "sensitivity_tornado.png")

    typer.echo(f"✅ Tüm grafikler başarıyla kaydedildi: {out_path}")


if __name__ == "__main__":
    app()
