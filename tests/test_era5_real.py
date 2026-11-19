"""ERA5-Land reanaliz indirme, dönüştürme, deaccumulation ve entegrasyon birim testleri.

Ağsız (offline) testler küçük sentetik NetCDF fixture'ları ve mock nesneleriyle yürütülür.
"""

import math
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from typer.testing import CliRunner

from twin.cli import app
from twin.data.era5 import (
    aggregate_hourly_to_daily,
    deaccumulate_era5_hourly,
    joules_m2_to_mj_m2,
    joules_m2_to_watts_m2,
    kelvin_to_celsius,
    load_era5_netcdf,
    meters_to_mm,
    relative_humidity_from_dewpoint,
    wind10m_to_wind2m,
)
from twin.data.era5_download import (
    DEFAULT_AREA,
    build_era5_request,
    check_cdsapirc,
    check_park_grid_overlap,
    download_era5_month,
)
from twin.sim.engine import prepare_season_weather

runner = CliRunner()


# ==============================================================================
# 1. BİRİM DÖNÜŞÜMLERİ VE FİZİKSEL FORMÜLLER
# ==============================================================================


def test_kelvin_to_celsius():
    """Kelvin - Santigrat dönüşümünü test eder."""
    assert kelvin_to_celsius(273.15) == pytest.approx(0.0, abs=1e-5)
    assert kelvin_to_celsius(300.0) == pytest.approx(26.85, abs=1e-2)
    assert kelvin_to_celsius(253.15) == pytest.approx(-20.0, abs=1e-5)

    arr = np.array([273.15, 293.15, 303.15])
    expected = np.array([0.0, 20.0, 30.0])
    np.testing.assert_allclose(kelvin_to_celsius(arr), expected, atol=1e-5)


def test_meters_to_mm():
    """Metre - Milimetre yağış dönüşümünü test eder."""
    assert meters_to_mm(0.005) == pytest.approx(5.0, abs=1e-5)
    assert meters_to_mm(0.0) == pytest.approx(0.0, abs=1e-5)
    assert meters_to_mm(0.0254) == pytest.approx(25.4, abs=1e-5)


def test_radiation_joules_conversions():
    """J/m2 -> MJ/m2 ve J/m2 -> W/m2 dönüşümlerini test eder."""
    # 1 saatlik 3.6e6 J/m2 -> 3.6 MJ/m2 ve 1000 W/m2
    j_val = 3.6e6
    assert joules_m2_to_mj_m2(j_val) == pytest.approx(3.6, abs=1e-5)
    assert joules_m2_to_watts_m2(j_val, dt_seconds=3600.0) == pytest.approx(1000.0, abs=1e-5)


def test_wind10m_to_wind2m():
    """FAO-56 Denklem 47 logaritmik rüzgâr profili indirgemesini test eder."""
    # u2 = u10 * 4.87 / ln(67.8*10 - 5.42) ≈ u10 * 0.7480
    factor = 4.87 / math.log(67.8 * 10.0 - 5.42)
    assert wind10m_to_wind2m(1.0) == pytest.approx(factor, rel=1e-4)
    assert wind10m_to_wind2m(2.0) == pytest.approx(2.0 * factor, rel=1e-4)
    assert wind10m_to_wind2m(0.0) == pytest.approx(0.0, abs=1e-5)


def test_relative_humidity_from_dewpoint():
    """Tetens / Magnus bağıl nem hesaplamasını test eder."""
    # T = Td durumunda bağıl nem %100 olmalıdır
    assert relative_humidity_from_dewpoint(20.0, 20.0) == pytest.approx(100.0, abs=1e-2)

    # T = 25°C, Td = 15°C -> RH yaklaşık %53.6
    rh = relative_humidity_from_dewpoint(25.0, 15.0)
    assert 50.0 < rh < 60.0

    # Uç değer sınırlandırması [0, 100]
    assert relative_humidity_from_dewpoint(10.0, 25.0) == 100.0  # Td > T fiziksel hatası
    assert relative_humidity_from_dewpoint(40.0, -20.0) >= 0.0


# ==============================================================================
# 2. BİRİKİMLİ DEĞİŞKENLER (DEACCUMULATION) VE SINIR TESTLERİ
# ==============================================================================


def test_deaccumulate_era5_hourly_standard_day():
    """Bir tam gün (24 saat) boyunca saatlik deaccumulation adımlarını test eder."""
    # 2024-04-01 01:00:00 -> 2024-04-02 00:00:00
    times = pd.date_range("2024-04-01 01:00", "2024-04-02 00:00", freq="h", tz="UTC")
    # Her saat 2 birim kümülatif artış: [2, 4, 6, ..., 48]
    accum_vals = np.arange(2, 50, 2, dtype=float)
    series = pd.Series(accum_vals, index=times)

    deaccum = deaccumulate_era5_hourly(series, times)

    # Her saatin ayrıştırılmış değeri tam 2.0 olmalıdır
    assert len(deaccum) == 24
    assert np.allclose(deaccum.values, 2.0)


def test_deaccumulate_era5_hourly_day_boundary_reset():
    """Günün 00 UTC -> 01 UTC sınırında kümülatif serinin sıfırlanmasını test eder."""
    times = pd.date_range("2024-04-01 22:00", "2024-04-02 03:00", freq="h", tz="UTC")
    # 22:00 -> 22, 23:00 -> 23, 00:00 -> 24 (1. gün sonu), 01:00 -> 1.5 (2. gün başı reset), 02:00 -> 3.5, 03:00 -> 5.0
    accum_vals = [22.0, 23.0, 24.0, 1.5, 3.5, 5.0]
    series = pd.Series(accum_vals, index=times)

    deaccum = deaccumulate_era5_hourly(series, times)

    # 22:00: ilk eleman -> 22.0
    # 23:00: 23 - 22 = 1.0
    # 00:00: 24 - 23 = 1.0 (önceki güne ait 24. saat artışı)
    # 01:00: reset saati -> 1.5 (fark alınmaz!)
    # 02:00: 3.5 - 1.5 = 2.0
    # 03:00: 5.0 - 3.5 = 1.5
    expected = [22.0, 1.0, 1.0, 1.5, 2.0, 1.5]
    np.testing.assert_allclose(deaccum.values, expected)


def test_deaccumulate_era5_hourly_month_boundary_and_clamping():
    """Ay geçişi ve negatif yuvarlama hatalarının 0'a kırpılmasını test eder."""
    times = pd.date_range("2024-04-30 23:00", "2024-05-01 02:00", freq="h", tz="UTC")
    # 23:00 -> 10.0, 00:00 -> 9.9999999 (sayısal gürültü), 01:00 -> 3.0, 02:00 -> 5.0
    accum_vals = [10.0, 9.9999999, 3.0, 5.0]
    series = pd.Series(accum_vals, index=times)

    deaccum = deaccumulate_era5_hourly(series, times, clamp_min=0.0)

    assert deaccum.iloc[1] == 0.0  # Negatif fark kırpıldı
    assert deaccum.iloc[2] == 3.0  # 01 UTC reset değeri
    assert deaccum.iloc[3] == 2.0  # 5.0 - 3.0


def test_deaccumulate_month_boundary_cross_month():
    """Ay başındaki 00 UTC değerinin bir önceki ayın son gününe ait olduğunu ve doğru deaccumulate edildiğini test eder."""
    # Mart 31 22:00 -> 23:00 -> Nisan 1 00:00 -> Nisan 1 01:00 -> Nisan 1 02:00
    times = pd.date_range("2024-03-31 22:00", "2024-04-01 02:00", freq="h", tz="UTC")
    # 22:00 -> 8.0 m, 23:00 -> 10.0 m, 00:00 (Nisan 1) -> 13.0 m (Mart 31 24. saat toplamı),
    # 01:00 (Nisan 1) -> 2.0 m (reset ilk saat), 02:00 (Nisan 1) -> 5.0 m
    accum_vals = [0.008, 0.010, 0.013, 0.002, 0.005]
    series = pd.Series(accum_vals, index=times)

    deaccum = deaccumulate_era5_hourly(series, times)

    # 23:00: 0.010 - 0.008 = 0.002 m
    # 00:00: 0.013 - 0.010 = 0.003 m (Mart 31 son saat yağışı)
    # 01:00: 0.002 m (Nisan 1 ilk saat, reset)
    # 02:00: 0.005 - 0.002 = 0.003 m
    assert deaccum.iloc[1] == pytest.approx(0.002, abs=1e-6)
    assert deaccum.iloc[2] == pytest.approx(0.003, abs=1e-6)
    assert deaccum.iloc[3] == pytest.approx(0.002, abs=1e-6)
    assert deaccum.iloc[4] == pytest.approx(0.003, abs=1e-6)


def test_deaccumulate_era5_hourly_isolated_month_start_00utc():
    """Önceki ay dosyası olmadan tek aylık dosya açıldığında (00:00 UTC ilk satır)
    önceki ayın kümülatif toplamının günün ilk gününe artış olarak yazılmadığını (0 yapıldığını) test eder."""
    # Temmuz 1 00:00 (Haziran 30 toplamı: 27.49 MJ), 01:00 (reset: 0.0), 02:00 (0.0), 03:00 (0.01)
    times = pd.date_range("2024-07-01 00:00", "2024-07-01 03:00", freq="h", tz="UTC")
    accum_vals = [27.493664, 0.0, 0.0, 0.011505]
    series = pd.Series(accum_vals, index=times)

    deaccum = deaccumulate_era5_hourly(series, times)

    # 00:00 UTC satırı serinin ilk elemanı olduğu için önceki ayın toplamıdır ve 0.0 olmalıdır
    assert deaccum.iloc[0] == 0.0
    # 01:00 UTC reset değeri doğrudan 0.0
    assert deaccum.iloc[1] == 0.0
    # 02:00 UTC fark: 0.0 - 0.0 = 0.0
    assert deaccum.iloc[2] == 0.0
    # 03:00 UTC fark: 0.011505 - 0.0 = 0.011505
    assert deaccum.iloc[3] == pytest.approx(0.011505, abs=1e-6)


# ==============================================================================
# 3. CDS API İNDİRME VE GÜVENLİK TESTLERİ (OFFLINE)
# ==============================================================================


def test_check_cdsapirc_missing(tmp_path, monkeypatch):
    """~/.cdsapirc dosyası olmadığında anlaşılır hata verilmesini ve durulmasını test eder."""
    non_existent = tmp_path / ".cdsapirc_not_found"
    with pytest.raises(FileNotFoundError, match="CDS API yapılandırma dosyası bulunamadı"):
        check_cdsapirc(non_existent)


def test_check_cdsapirc_valid(tmp_path):
    """Geçerli biçimdeki ~/.cdsapirc dosyasını doğrular."""
    rc_file = tmp_path / ".cdsapirc"
    rc_file.write_text(
        "url: https://cds.climate.copernicus.eu/api\nkey: mock-secret-token\n", encoding="utf-8"
    )
    assert check_cdsapirc(rc_file) == rc_file


def test_check_cdsapirc_invalid_empty(tmp_path):
    """Boş ~/.cdsapirc dosyasında hata fırlatıldığını test eder."""
    rc_file = tmp_path / ".cdsapirc"
    rc_file.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="boş"):
        check_cdsapirc(rc_file)


def test_build_era5_request():
    """CDS API istek sözlüğünün beklenen değişken ve zaman yapısını test eder."""
    req = build_era5_request(2024, 7, area=DEFAULT_AREA)

    assert req["dataset"] == "reanalysis-era5-land"
    assert req["year"] == "2024"
    assert req["month"] == "07"
    assert len(req["time"]) == 24
    assert req["time"][0] == "00:00"
    assert req["time"][-1] == "23:00"
    assert len(req["day"]) == 31
    assert req["data_format"] == "netcdf"
    assert req["download_format"] == "unarchived"
    assert req["area"] == DEFAULT_AREA
    for var in [
        "2m_temperature",
        "2m_dewpoint_temperature",
        "total_precipitation",
        "surface_solar_radiation_downwards",
        "volumetric_soil_water_layer_1",
    ]:
        assert var in req["variable"]


def test_download_era5_retry_and_backoff(tmp_path):
    """Başarısız istekte 3 deneme yapıldığını ve ardından hata raporlandığını test eder."""
    mock_client = MagicMock()
    mock_client.retrieve.side_effect = ConnectionError("CDS sunucu bağlantı hatası")

    with pytest.raises(RuntimeError, match="3 deneme sonrasında başarısız oldu"):
        download_era5_month(
            year=2024,
            month=6,
            out_dir=tmp_path,
            client=mock_client,
            max_retries=3,
            backoff_seconds=0.01,  # Hızlı test
        )

    assert mock_client.retrieve.call_count == 3


def test_download_era5_skips_existing_file(tmp_path):
    """Daha önce indirilmiş dosyanın yeniden indirilmediğini test eder."""
    existing_file = tmp_path / "era5land_2024_06.nc"
    existing_file.write_bytes(b"dummy netcdf content")

    mock_client = MagicMock()
    p = download_era5_month(2024, 6, out_dir=tmp_path, client=mock_client)

    assert p == existing_file
    mock_client.retrieve.assert_not_called()


def test_download_era5_month_variable_grouping_and_merge(tmp_path):
    """Değişken gruplarına bölerek indirme ve xarray ile birleştirme akışını test eder."""
    mock_client = MagicMock()

    def mock_retrieve(dataset, req, target):
        times = pd.date_range("2024-04-01 00:00", "2024-04-01 02:00", freq="h")
        vars_dict = {
            v: (("valid_time", "latitude", "longitude"), np.ones((len(times), 1, 1), dtype=float))
            for v in req["variable"]
        }
        ds = xr.Dataset(
            data_vars=vars_dict,
            coords={"valid_time": times, "latitude": [41.05], "longitude": [29.01]},
        )
        ds.to_netcdf(target)

    mock_client.retrieve.side_effect = mock_retrieve

    groups = [
        ["2m_temperature", "surface_pressure"],
        ["total_precipitation"],
    ]

    out_file = download_era5_month(
        year=2024,
        month=4,
        out_dir=tmp_path,
        client=mock_client,
        variable_groups=groups,
    )

    assert out_file.exists()
    assert mock_client.retrieve.call_count == 2

    # Birleştirilmiş NetCDF içeriğini doğrula
    with xr.open_dataset(out_file) as merged:
        assert "2m_temperature" in merged.data_vars
        assert "surface_pressure" in merged.data_vars
        assert "total_precipitation" in merged.data_vars


def test_download_era5_adaptive_split_on_403_cost_limit(tmp_path):
    """CDS 403 cost limits / too large hatasında isteğin otomatik günlere bölündüğünü test eder."""
    mock_client = MagicMock()

    def mock_retrieve_with_cost_limit(dataset, req, target):
        days = req.get("day", [])
        if len(days) > 2:
            # Büyük istekte 403 hatası simüle et
            raise Exception("403 Client Error: Your request is too large (cost limits exceeded).")

        # Parçalanmış istek başarılı
        times = pd.date_range("2024-04-01 00:00", periods=len(days) * 24, freq="h")
        vars_dict = {
            v: (("valid_time", "latitude", "longitude"), np.ones((len(times), 1, 1), dtype=float))
            for v in req["variable"]
        }
        ds = xr.Dataset(
            data_vars=vars_dict,
            coords={"valid_time": times, "latitude": [41.05], "longitude": [29.01]},
        )
        ds.to_netcdf(target)

    mock_client.retrieve.side_effect = mock_retrieve_with_cost_limit

    groups = [["total_precipitation"]]

    out_file = download_era5_month(
        year=2024,
        month=4,
        out_dir=tmp_path,
        client=mock_client,
        variable_groups=groups,
    )

    assert out_file.exists()
    assert out_file.stat().st_size > 0


def test_check_park_grid_overlap():
    """Yıldız ve Maçka parklarının 0.1° ERA5-Land ızgarasında aynı hücreye düştüğünü teyit eder."""
    overlap = check_park_grid_overlap(grid_res_deg=0.10)
    assert overlap is True


# ==============================================================================
# 4. SENTETİK NetCDF DOSYASI İLE OKUMA VE PARSE TESTLERİ
# ==============================================================================


@pytest.fixture
def synthetic_netcdf_fixture(tmp_path) -> Path:
    """xarray ile 10 değişkenli ve 2D ızgaralı küçük bir ERA5-Land NetCDF dosyası üretir."""
    nc_path = tmp_path / "era5land_2024_04.nc"

    times = pd.date_range("2024-04-01 00:00", "2024-04-05 23:00", freq="h")
    lats = [41.1, 41.0]
    lons = [28.9, 29.0, 29.1]

    shape = (len(times), len(lats), len(lons))

    # Kümülatif yağış ve radyasyon (saatlik artan)
    t_idx = np.arange(len(times), dtype=float)[:, None, None]
    tp_accum = np.broadcast_to(t_idx * 0.0002, shape).copy()  # m
    ssrd_accum = np.broadcast_to(t_idx * 50000.0, shape).copy()  # J/m2

    ds = xr.Dataset(
        data_vars={
            "t2m": (("valid_time", "latitude", "longitude"), np.full(shape, 293.15)),  # 20 °C
            "d2m": (("valid_time", "latitude", "longitude"), np.full(shape, 283.15)),  # 10 °C
            "u10": (("valid_time", "latitude", "longitude"), np.full(shape, 2.0)),
            "v10": (("valid_time", "latitude", "longitude"), np.full(shape, 1.5)),
            "sp": (("valid_time", "latitude", "longitude"), np.full(shape, 101325.0)),
            "tp": (("valid_time", "latitude", "longitude"), tp_accum),
            "ssrd": (("valid_time", "latitude", "longitude"), ssrd_accum),
            "swvl1": (("valid_time", "latitude", "longitude"), np.full(shape, 0.28)),
            "swvl2": (("valid_time", "latitude", "longitude"), np.full(shape, 0.25)),
        },
        coords={
            "valid_time": times,
            "latitude": lats,
            "longitude": lons,
        },
    )

    ds.to_netcdf(nc_path)
    return nc_path


def test_load_era5_netcdf(synthetic_netcdf_fixture):
    """Sentetik NetCDF dosyasını okur, en yakın koordinat hücresini seçer ve değişkenleri doğrular."""
    df = load_era5_netcdf(synthetic_netcdf_fixture, park_id="yildiz")

    assert len(df) == 120  # 5 gün * 24 saat
    assert "temp_c" in df.columns
    assert "dewpoint_c" in df.columns
    assert "rh_pct" in df.columns
    assert "wind_speed_2m_ms" in df.columns
    assert "rain_mm" in df.columns
    assert "rad_mj_m2" in df.columns
    assert "volumetric_soil_water_layer_1" in df.columns

    # Sıcaklık 20 °C
    assert df["temp_c"].iloc[0] == pytest.approx(20.0, abs=1e-2)
    assert df["dewpoint_c"].iloc[0] == pytest.approx(10.0, abs=1e-2)

    # Yağış pozitif ve deaccumulate edilmiş
    assert (df["rain_mm"] >= 0).all()
    assert (df["rad_mj_m2"] >= 0).all()


def test_aggregate_hourly_to_daily_with_soil_layers(synthetic_netcdf_fixture):
    """Günlük toplama işleminde toprak nemi katmanlarının ve FAO değişkenlerinin oluştuğunu test eder."""
    hourly_df = load_era5_netcdf(synthetic_netcdf_fixture, park_id="macka")
    daily_df = aggregate_hourly_to_daily(hourly_df)

    assert len(daily_df) == 5
    assert "temp_mean" in daily_df.columns
    assert "temp_max" in daily_df.columns
    assert "temp_min" in daily_df.columns
    assert "rh_mean" in daily_df.columns
    assert "rain_mm" in daily_df.columns
    assert "rad_mj_m2" in daily_df.columns
    assert "swvl1" in daily_df.columns
    assert "swvl2" in daily_df.columns

    assert daily_df["temp_mean"].iloc[0] == pytest.approx(20.0, abs=1e-2)
    assert daily_df["swvl1"].iloc[0] == pytest.approx(0.28, abs=1e-2)


# ==============================================================================
# 5. ENTEGRASYON VE DOĞRULAMA (prepare_season_weather & CLI)
# ==============================================================================


def test_prepare_season_weather_synthetic_default():
    """Varsayılan synthetic kaynağının geriye uyumlu çalıştığını doğrular."""
    df = prepare_season_weather(season_year=2024, source="synthetic", park_id="yildiz")
    assert len(df) == 214  # 1 Nisan - 31 Ekim
    assert "eto_mm" in df.columns
    assert df.attrs.get("source") == "synthetic"


def test_prepare_season_weather_era5_raises_when_missing():
    """ERA5 seçildiğinde veri yoksa sessizce sentetiğe DÜŞMEDEN FileNotFoundError fırlatıldığını test eder."""
    with pytest.raises(FileNotFoundError, match="ERA5 verisi bulunamadı"):
        prepare_season_weather(
            season_year=1999,
            source="era5",
            park_id="yildiz",
            raw_dir="data/raw/era5_non_existent",
            processed_dir="data/processed_non_existent",
        )


def test_prepare_season_weather_era5_loads_from_processed(tmp_path):
    """İşlenmiş CSV dosyasının prepare_season_weather(source='era5') ile başarıyla yüklendiğini test eder."""
    times = pd.date_range("2024-04-01", "2024-10-31", freq="D")
    dummy_daily = pd.DataFrame(
        {
            "temp_mean": np.full(len(times), 22.0),
            "temp_max": np.full(len(times), 27.0),
            "temp_min": np.full(len(times), 17.0),
            "rh_mean": np.full(len(times), 65.0),
            "rh_max": np.full(len(times), 85.0),
            "rh_min": np.full(len(times), 45.0),
            "wind_speed_2m_ms": np.full(len(times), 2.1),
            "pressure_kpa": np.full(len(times), 101.3),
            "rain_mm": np.full(len(times), 0.5),
            "rad_mj_m2": np.full(len(times), 18.5),
            "rad_wm2": np.full(len(times), 214.0),
            "eto_mm": np.full(len(times), 4.2),
        },
        index=times,
    )
    dummy_daily.index.name = "time"
    csv_file = tmp_path / "era5_yildiz_2024.csv"
    dummy_daily.to_csv(csv_file)

    loaded_df = prepare_season_weather(
        season_year=2024,
        source="era5",
        park_id="yildiz",
        processed_dir=tmp_path,
    )

    assert len(loaded_df) == 214
    assert loaded_df["eto_mm"].iloc[0] == pytest.approx(4.2, abs=1e-2)
    assert loaded_df.attrs.get("source") == "era5"


def test_physical_plausibility():
    """Fiziksel makullük aralıklarını test eder."""
    df = prepare_season_weather(season_year=2024, source="synthetic", park_id="yildiz")

    # 1. Günlük ETo Nisan-Ekim için 0-9 mm/gün
    assert (df["eto_mm"] >= 0.0).all()
    assert (df["eto_mm"] <= 9.0).all()

    # 2. Yaz ortalaması (Haziran-Ağustos) İstanbul için yaklaşık 4-6 mm/gün
    summer_df = df.loc["2024-06-01":"2024-08-31"]
    summer_eto_mean = summer_df["eto_mm"].mean()
    assert 3.5 <= summer_eto_mean <= 6.5

    # 3. Negatif yağış yok
    assert (df["rain_mm"] >= 0.0).all()

    # 4. Güneş radyasyonu 0-35 MJ/m2/gün
    assert (df["rad_mj_m2"] >= 0.0).all()
    assert (df["rad_mj_m2"] <= 35.0).all()


def test_real_era5land_july_2024_expected_rs_values():
    """Gerçek Temmuz 2024 NetCDF dosyası mevcutsa 1-4 Temmuz ve aylık Rs beklenen değerlerini doğrular."""
    nc_path = Path("data/raw/era5/era5land_2024_07.nc")
    if not nc_path.is_file():
        pytest.skip("data/raw/era5/era5land_2024_07.nc dosyası mevcut değil, test atlandı.")

    from twin.data.era5 import aggregate_hourly_to_daily, load_era5_netcdf

    hourly_df = load_era5_netcdf(nc_path, park_id="yildiz")
    daily_df = aggregate_hourly_to_daily(hourly_df)

    # 1-4 Temmuz beklenen günlük Rs değerleri: 28.34, 28.86, 23.64, 20.24 MJ/m2
    assert daily_df.loc["2024-07-01", "rad_mj_m2"] == pytest.approx(28.34, abs=0.02)
    assert daily_df.loc["2024-07-02", "rad_mj_m2"] == pytest.approx(28.86, abs=0.02)
    assert daily_df.loc["2024-07-03", "rad_mj_m2"] == pytest.approx(23.64, abs=0.02)
    assert daily_df.loc["2024-07-04", "rad_mj_m2"] == pytest.approx(20.24, abs=0.02)

    # Temmuz ayı günlük ortalama Rs değeri: 24.72 MJ/m2/gün
    assert daily_df["rad_mj_m2"].mean() == pytest.approx(24.72, abs=0.02)


def test_real_era5land_non_telescoping_mass_conservation():
    """Gerçek Temmuz 2024 NetCDF dosyasında teleskopik olmayan günlük kütle/enerji korunumu ve pozitiflik testi."""
    nc_path = Path("data/raw/era5/era5land_2024_07.nc")
    if not nc_path.is_file():
        pytest.skip("data/raw/era5/era5land_2024_07.nc dosyası mevcut değil, test atlandı.")

    import xarray as xr

    ds = xr.open_dataset(nc_path)
    ds_pt = ds.sel(latitude=41.0484, longitude=29.0159, method="nearest")
    times = pd.to_datetime(ds_pt.valid_time.values)

    # 1. Yağış (tp) için kütle korunumu (metre cinsinden, fark < 1e-6)
    raw_tp = pd.Series(ds_pt["tp"].values, index=times)
    deaccum_tp = deaccumulate_era5_hourly(raw_tp, times, clamp_min=0.0)

    # Tüm saatlik artışlar >= 0 olmalıdır
    assert (deaccum_tp >= 0.0).all()

    for d in range(1, 31):
        day_str = f"2024-07-{d:02d}"
        next_day_str = f"2024-07-{d+1:02d}"
        t_start = pd.Timestamp(f"{day_str} 01:00:00")
        t_end = pd.Timestamp(f"{next_day_str} 00:00:00")
        day_sum = deaccum_tp.loc[t_start:t_end].sum()
        raw_target = raw_tp.loc[t_end]
        assert day_sum == pytest.approx(raw_target, abs=1e-6), (
            f"Yağış {day_str} toplamı {day_sum} != {raw_target}"
        )

    # 2. Güneş radyasyonu (ssrd) için enerji korunumu (MJ/m2 cinsinden, fark < 1e-5)
    raw_ssrd_mj = pd.Series(ds_pt["ssrd"].values / 1.0e6, index=times)
    deaccum_ssrd_mj = deaccumulate_era5_hourly(raw_ssrd_mj, times, clamp_min=0.0)

    # Tüm saatlik radyasyon artışları >= 0 olmalıdır
    assert (deaccum_ssrd_mj >= 0.0).all()

    for d in range(1, 31):
        day_str = f"2024-07-{d:02d}"
        next_day_str = f"2024-07-{d+1:02d}"
        t_start = pd.Timestamp(f"{day_str} 01:00:00")
        t_end = pd.Timestamp(f"{next_day_str} 00:00:00")
        day_sum = deaccum_ssrd_mj.loc[t_start:t_end].sum()
        raw_target = raw_ssrd_mj.loc[t_end]
        assert day_sum == pytest.approx(raw_target, abs=1e-5), (
            f"Radyasyon {day_str} toplamı {day_sum} != {raw_target}"
        )


def test_cli_era5_download_help():
    """twin era5 download --help komutunu test eder."""
    res = runner.invoke(app, ["era5", "download", "--help"])
    assert res.exit_code == 0
    assert "--park" in res.output
    assert "--years" in res.output
    assert "--months" in res.output


def test_cli_era5_build_empty_dir(tmp_path):
    """twin era5 build komutunun boş dizinde uyarı verip güvenle sonlandığını test eder."""
    res = runner.invoke(
        app, ["era5", "build", "--raw-dir", str(tmp_path), "--out-dir", str(tmp_path / "proc")]
    )
    assert res.exit_code == 0
    assert "NetCDF dosyası bulunamadı" in res.output


# ==============================================================================
# 6. REST API ENTEGRASYON TESTLERİ
# ==============================================================================


def test_api_weather_source_synthetic():
    """REST API /weather uç noktasının source='synthetic' yanıtını doğrular."""
    import os

    from fastapi.testclient import TestClient

    from twin.api.app import app as fastapi_app

    os.environ["API_AUTH_TOKEN"] = "test_token_era5"
    client = TestClient(fastapi_app)
    headers = {"Authorization": "Bearer test_token_era5"}

    res = client.get("/weather?park_id=yildiz&season=2024&source=synthetic", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 214
    assert data[0]["source"] == "synthetic"
    assert "eto_mm" in data[0]


def test_api_weather_source_era5_missing():
    """REST API /weather uç noktasının era5 seçilip dosya olmadığında 404 döneceğini test eder."""
    import os

    from fastapi.testclient import TestClient

    from twin.api.app import app as fastapi_app

    os.environ["API_AUTH_TOKEN"] = "test_token_era5"
    client = TestClient(fastapi_app)
    headers = {"Authorization": "Bearer test_token_era5"}

    res = client.get("/weather?park_id=yildiz&season=1999&source=era5", headers=headers)
    assert res.status_code == 404
    assert "ERA5 verisi bulunamadı" in res.json()["detail"]


def test_api_simulate_source_synthetic():
    """REST API /simulate uç noktasının source alanını dönmesini test eder."""
    import os

    from fastapi.testclient import TestClient

    from twin.api.app import app as fastapi_app

    os.environ["API_AUTH_TOKEN"] = "test_token_era5"
    client = TestClient(fastapi_app)
    headers = {"Authorization": "Bearer test_token_era5"}

    payload = {"park_id": "yildiz", "season": 2024, "strategy": "S4", "source": "synthetic"}
    res = client.post("/simulate", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["source"] == "synthetic"
    assert "metrics" in data


# ==============================================================================
# 7. source="auto": GERÇEK ERA5 ÖNCELİKLİ, YOKSA ETİKETLİ SENTETİK
# ==============================================================================

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_CSV_2024 = REPO_ROOT / "data" / "processed" / "era5_yildiz_2024.csv"


def test_prepare_season_weather_auto_reads_csv_eto_exactly(tmp_path):
    """auto kaynağı CSV'yi okur; eto_mm sütunu yeniden hesaplanmadan birebir korunur."""
    times = pd.date_range("2024-03-30", "2024-11-02", freq="D", tz="UTC")
    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {"eto_mm": rng.uniform(1.0, 7.0, len(times)), "rain_mm": rng.uniform(0, 5, len(times))},
        index=times,
    )
    df.index.name = "time"
    df.to_csv(tmp_path / "era5_yildiz_2024.csv")

    loaded = prepare_season_weather(season_year=2024, park_id="yildiz", processed_dir=tmp_path)

    on_disk = pd.read_csv(tmp_path / "era5_yildiz_2024.csv", index_col=0, parse_dates=True)
    expected = on_disk.loc["2024-04-01":"2024-10-31", "eto_mm"]
    assert loaded.attrs["source"] == "era5"
    assert len(loaded) == 214
    np.testing.assert_array_equal(loaded["eto_mm"].to_numpy(), expected.to_numpy())


def test_prepare_season_weather_auto_falls_back_with_warning(tmp_path):
    """auto kaynağında yıl dosyası yoksa uyarı verilir ve çıktı 'synthetic' etiketlenir."""
    with pytest.warns(UserWarning, match="SENTETİK"):
        df = prepare_season_weather(season_year=1999, park_id="yildiz", processed_dir=tmp_path)
    assert df.attrs["source"] == "synthetic"
    assert len(df) == 214


def test_prepare_season_weather_invalid_source():
    with pytest.raises(ValueError, match="Geçersiz veri kaynağı"):
        prepare_season_weather(season_year=2024, source="ecmwf")


@pytest.mark.skipif(not REAL_CSV_2024.is_file(), reason="Gerçek ERA5 2024 CSV yok")
def test_prepare_season_weather_auto_real_2024_matches_csv():
    """Depodaki gerçek 2024 CSV'si: auto ile yüklenen ETo, CSV sütunuyla birebir aynı."""
    loaded = prepare_season_weather(season_year=2024, park_id="yildiz", processed_dir=REAL_CSV_2024.parent)
    csv = pd.read_csv(REAL_CSV_2024, index_col=0, parse_dates=True)
    csv = csv.loc[(csv.index >= "2024-04-01") & (csv.index <= "2024-10-31")]
    assert loaded.attrs["source"] == "era5"
    assert len(loaded) == len(csv)
    np.testing.assert_array_equal(loaded["eto_mm"].to_numpy(), csv["eto_mm"].to_numpy())


def test_api_simulate_auto_missing_year_reports_synthetic(monkeypatch):
    """/simulate varsayılan (auto) kaynakta, yıl yoksa yanıtta çözümlenen 'synthetic' görünür."""
    from fastapi.testclient import TestClient

    from twin.api.app import app as fastapi_app

    monkeypatch.setenv("API_AUTH_TOKEN", "test_token_era5")
    monkeypatch.chdir(REPO_ROOT)
    client = TestClient(fastapi_app)
    headers = {"Authorization": "Bearer test_token_era5"}

    with pytest.warns(UserWarning):
        res = client.post("/simulate", json={"season": 1999, "strategy": "S0"}, headers=headers)
    assert res.status_code == 200
    assert res.json()["source"] == "synthetic"


@pytest.mark.skipif(not REAL_CSV_2024.is_file(), reason="Gerçek ERA5 2024 CSV yok")
def test_api_compare_and_cli_auto_report_era5(monkeypatch):
    """Gerçek CSV varken /compare yanıtı ve 'twin compare' çıktısı kaynağı 'era5' gösterir."""
    from fastapi.testclient import TestClient

    from twin.api.app import app as fastapi_app

    monkeypatch.setenv("API_AUTH_TOKEN", "test_token_era5")
    monkeypatch.chdir(REPO_ROOT)
    client = TestClient(fastapi_app)
    headers = {"Authorization": "Bearer test_token_era5"}

    res = client.post("/compare", json={"season": 2024}, headers=headers)
    assert res.status_code == 200
    assert res.json()["source"] == "era5"

    cli_res = runner.invoke(app, ["compare", "--season", "2024"])
    assert cli_res.exit_code == 0
    assert "Hava verisi kaynağı: era5" in cli_res.output
