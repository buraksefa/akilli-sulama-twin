"""ECMWF ERA5-Land saatlik reanaliz verisi indirme modülü.

Copernicus Climate Data Store (CDS) yeni API (cds.climate.copernicus.eu/api)
kullanılarak ay bazında NetCDF dosyalarını indirir.

CDS 403 Cost Limits & İstek Boyutu Yönetimi:
- Büyük istekler değişken gruplarına bölünerek indirilir (5 grup) ve xarray ile tek ay dosyasında birleştirilir.
- 403 "cost limits exceeded / request too large" hatası alındığında istek otomatik olarak
  gün ve değişken bazında alt parçalara bölünür.
- Geçici ağ ve 5xx hatalarında üstel geri çekilme (exponential backoff) ile azami 3 deneme yapılır.

Güvenlik Kuralı:
- cdsapi kimlik bilgisi ~/.cdsapirc dosyasından okunur.
- API anahtarları asla koda, repoya, loglara veya dokümanlara yazılmaz.
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import xarray as xr

from twin.config import DEFAULT_CONFIG

logger = logging.getLogger(__name__)

# Sabitler config.py üzerindeki ParameterItem tanımlarından okunur
_ERA5_CFG = DEFAULT_CONFIG.era5

DEFAULT_AREA: List[float] = [
    float(_ERA5_CFG.area_north.value),
    float(_ERA5_CFG.area_west.value),
    float(_ERA5_CFG.area_south.value),
    float(_ERA5_CFG.area_east.value),
]

ERA5_LAND_VARIABLES: List[str] = [
    "2m_temperature",
    "2m_dewpoint_temperature",
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
    "surface_pressure",
    "total_precipitation",
    "surface_solar_radiation_downwards",
    "surface_thermal_radiation_downwards",
    "volumetric_soil_water_layer_1",
    "volumetric_soil_water_layer_2",
]

# CDS maliyet ve boyut sınırını (403 cost limit) aşmamak için optimize edilmiş değişken grupları
ERA5_VARIABLE_GROUPS: List[List[str]] = [
    [
        "2m_temperature",
        "2m_dewpoint_temperature",
        "surface_pressure",
        "10m_u_component_of_wind",
        "10m_v_component_of_wind",
    ],
    [
        "total_precipitation",
        "surface_solar_radiation_downwards",
        "surface_thermal_radiation_downwards",
        "volumetric_soil_water_layer_1",
        "volumetric_soil_water_layer_2",
    ],
]

PARK_COORDINATES: Dict[str, Tuple[float, float]] = {
    "yildiz": (float(_ERA5_CFG.yildiz_lat.value), float(_ERA5_CFG.yildiz_lon.value)),
    "macka": (float(_ERA5_CFG.macka_lat.value), float(_ERA5_CFG.macka_lon.value)),
}


def check_cdsapirc(rc_path: Optional[Union[str, Path]] = None) -> Path:
    """~/.cdsapirc dosyasının varlığını ve temel biçimini doğrular.

    Dosya bulunamazsa anlaşılır bir hata verir ve durur.
    API anahtarı kesinlikle okunup loglanmaz veya döndürülmez.
    """
    path = Path(rc_path) if rc_path else Path.home() / ".cdsapirc"
    if not path.is_file():
        raise FileNotFoundError(
            f"CDS API yapılandırma dosyası bulunamadı ({path}).\n"
            "Lütfen https://cds.climate.copernicus.eu adresinde hesap oluşturup giriş yapın.\n"
            "Kullanıcı profilinizden temin edeceğiniz 'Personal Access Token' bilgisini ~/.cdsapirc dosyasına şu biçimde ekleyin:\n"
            "url: https://cds.climate.copernicus.eu/api\n"
            "key: <KİŞİSEL_ERİŞİM_ANAHTARINIZ>"
        )

    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(
            f"CDS API yapılandırma dosyası ({path}) boş. Lütfen geçerli url ve key satırlarını ekleyin."
        )

    lines = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")]
    has_url = any(line.startswith("url:") for line in lines)
    has_key = any(line.startswith("key:") for line in lines)

    if not (has_url and has_key):
        raise ValueError(
            f"CDS API yapılandırma dosyası ({path}) eksik alan içeriyor. 'url:' ve 'key:' tanımları gereklidir."
        )

    return path


def check_park_grid_overlap(
    grid_res_deg: float = 0.10,
) -> bool:
    """Yıldız ve Maçka parklarının aynı 0.1° ERA5-Land ızgara hücresine düşüp düşmediğini kontrol eder."""
    y_lat, y_lon = PARK_COORDINATES["yildiz"]
    m_lat, m_lon = PARK_COORDINATES["macka"]

    y_grid = (round(y_lat / grid_res_deg) * grid_res_deg, round(y_lon / grid_res_deg) * grid_res_deg)
    m_grid = (round(m_lat / grid_res_deg) * grid_res_deg, round(m_lon / grid_res_deg) * grid_res_deg)

    same_cell = y_grid == m_grid
    if same_cell:
        logger.info(
            "ERA5-Land ızgara çözünürlüğü 0.1° (~9 km) olduğundan, Yıldız (%s, %s) "
            "ve Maçka (%s, %s) parkları aynı ızgara hücresine (%s, %s) denk gelmektedir.",
            y_lat,
            y_lon,
            m_lat,
            m_lon,
            round(y_grid[0], 2),
            round(y_grid[1], 2),
        )
    return same_cell


def is_cost_limit_error(exception: Exception) -> bool:
    """Hatanın CDS 403 maliyet/boyut sınırından kaynaklanıp kaynaklanmadığını tespit eder."""
    msg = str(exception).lower()
    return (
        "403" in msg
        or "cost limit" in msg
        or "cost limits exceeded" in msg
        or "request is too large" in msg
        or "too large" in msg
        or "limit exceeded" in msg
    )


def build_era5_request(
    year: int,
    month: int,
    area: Optional[List[float]] = None,
    variables: Optional[List[str]] = None,
    days: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Tek bir yıl ve ay için CDS API istek sözlüğünü oluşturur."""
    req_area = area if area is not None else DEFAULT_AREA
    req_vars = variables if variables is not None else ERA5_LAND_VARIABLES
    req_days = days if days is not None else [f"{d:02d}" for d in range(1, 32)]

    return {
        "dataset": str(_ERA5_CFG.dataset.value),
        "variable": req_vars,
        "year": f"{year:04d}",
        "month": f"{month:02d}",
        "day": req_days,
        "time": [f"{h:02d}:00" for h in range(24)],
        "area": req_area,
        "data_format": "netcdf",
        "download_format": "unarchived",
    }


def _retrieve_chunk_with_adaptive_split(
    client: Any,
    dataset_name: str,
    req: Dict[str, Any],
    target_nc: Path,
    max_retries: int = 3,
    backoff_seconds: float = 5.0,
) -> Path:
    """Tek bir istek parçasını indirir; 403 durumunda gün/değişken bazında otomatik böler."""
    if target_nc.exists() and target_nc.stat().st_size > 0:
        logger.info("Geçici parça dosyası zaten mevcut, atlanıyor: %s", target_nc)
        return target_nc

    days = list(req.get("day", []))
    vars_list = list(req.get("variable", []))

    # Eğer tek parça indirme denemesi yapılacaksa
    last_error: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(
                "CDS İndirme isteği yapılıyor: Değişkenler=%s, Günler=%d gün (Deneme %d/%d)...",
                vars_list,
                len(days),
                attempt,
                max_retries,
            )
            client.retrieve(dataset_name, req, str(target_nc))
            if target_nc.exists() and target_nc.stat().st_size > 0:
                return target_nc
            raise RuntimeError(f"İndirme tamamlandı ancak dosya boş: {target_nc}")
        except Exception as e:
            last_error = e
            if is_cost_limit_error(e):
                logger.warning("⚠️ CDS 403 maliyet/boyut sınırı aşıldı (%s). İstek parçalanıyor...", e)
                # 403 hatasında tekrar deneme yerine doğrudan bölme stratejisine geç
                break

            logger.warning(
                "Geçici CDS indirme hatası (%s, Deneme %d/%d): %s", req.get("month"), attempt, max_retries, e
            )
            if attempt < max_retries:
                sleep_time = backoff_seconds * (2 ** (attempt - 1))
                time.sleep(sleep_time)

    # 403 veya çözülemeyen hata durumunda istek parçalama
    if is_cost_limit_error(last_error or Exception()):
        # 1. Öncelik: Günleri ikiye böl
        if len(days) > 1:
            mid = len(days) // 2
            days_part1 = days[:mid]
            days_part2 = days[mid:]

            temp_p1 = target_nc.with_name(f"{target_nc.stem}_d1.nc")
            temp_p2 = target_nc.with_name(f"{target_nc.stem}_d2.nc")

            req1 = dict(req, day=days_part1)
            req2 = dict(req, day=days_part2)

            _retrieve_chunk_with_adaptive_split(
                client, dataset_name, req1, temp_p1, max_retries, backoff_seconds
            )
            _retrieve_chunk_with_adaptive_split(
                client, dataset_name, req2, temp_p2, max_retries, backoff_seconds
            )

            # İki zaman parçasını birleştir
            with xr.open_dataset(temp_p1) as ds1, xr.open_dataset(temp_p2) as ds2:
                time_dim = "valid_time" if "valid_time" in ds1.coords else "time"
                combined = xr.concat([ds1, ds2], dim=time_dim)
                combined.to_netcdf(target_nc)

            # Geçici dosyaları temizle
            temp_p1.unlink(missing_ok=True)
            temp_p2.unlink(missing_ok=True)
            return target_nc

        # 2. Öncelik: Gün zaten 1 ise değişkenleri ikiye böl
        if len(vars_list) > 1:
            mid_v = len(vars_list) // 2
            vars_part1 = vars_list[:mid_v]
            vars_part2 = vars_list[mid_v:]

            temp_v1 = target_nc.with_name(f"{target_nc.stem}_v1.nc")
            temp_v2 = target_nc.with_name(f"{target_nc.stem}_v2.nc")

            req_v1 = dict(req, variable=vars_part1)
            req_v2 = dict(req, variable=vars_part2)

            _retrieve_chunk_with_adaptive_split(
                client, dataset_name, req_v1, temp_v1, max_retries, backoff_seconds
            )
            _retrieve_chunk_with_adaptive_split(
                client, dataset_name, req_v2, temp_v2, max_retries, backoff_seconds
            )

            with xr.open_dataset(temp_v1) as ds1, xr.open_dataset(temp_v2) as ds2:
                combined = xr.merge([ds1, ds2])
                combined.to_netcdf(target_nc)

            temp_v1.unlink(missing_ok=True)
            temp_v2.unlink(missing_ok=True)
            return target_nc

    raise RuntimeError(
        f"ERA5-Land indirmesi {max_retries} deneme sonrasında başarısız oldu ({req.get('year')}-{req.get('month')}): {last_error}"
    )


def download_era5_month(
    year: int,
    month: int,
    out_dir: Union[str, Path] = "data/raw/era5",
    area: Optional[List[float]] = None,
    client: Optional[Any] = None,
    max_retries: int = 3,
    backoff_seconds: float = 5.0,
    variable_groups: Optional[List[List[str]]] = None,
) -> Path:
    """Belirtilen yıl ve ay için ERA5-Land NetCDF dosyasını değişken gruplarına bölerek indirir ve birleştirir.

    Var olan dosyaları tekrar indirmez. 403 boyut sınırında istekleri otomatik parçalar.
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    target_file = out_path / f"era5land_{year:04d}_{month:02d}.nc"

    if target_file.exists() and target_file.stat().st_size > 0:
        logger.info("Dosya zaten mevcut, atlanıyor: %s", target_file)
        return target_file

    if client is None:
        check_cdsapirc()
        try:
            import cdsapi

            client = cdsapi.Client()
        except ImportError as e:
            raise ImportError("cdsapi paketi kurulu değil. Lütfen 'pip install cdsapi' çalıştırın.") from e

    groups = variable_groups or ERA5_VARIABLE_GROUPS
    temp_group_files: List[Path] = []

    try:
        for g_idx, group_vars in enumerate(groups, start=1):
            temp_nc = out_path / f"_tmp_era5land_{year:04d}_{month:02d}_g{g_idx}.nc"
            req = build_era5_request(year=year, month=month, area=area, variables=group_vars)
            dataset_name = req.pop("dataset", "reanalysis-era5-land")

            logger.info("Grup %d/%d indiriliyor (%s)...", g_idx, len(groups), group_vars)
            _retrieve_chunk_with_adaptive_split(
                client=client,
                dataset_name=dataset_name,
                req=req,
                target_nc=temp_nc,
                max_retries=max_retries,
                backoff_seconds=backoff_seconds,
            )
            temp_group_files.append(temp_nc)

        # Tüm grupları tek bir aylık NetCDF dosyasında birleştir (xarray merge)
        logger.info("Değişken grupları birleştiriliyor -> %s", target_file)
        group_datasets = [xr.open_dataset(p) for p in temp_group_files]
        try:
            merged_ds = xr.merge(group_datasets, compat="override")
            merged_ds.to_netcdf(target_file)
        finally:
            for ds in group_datasets:
                ds.close()

        # Birleştirme başarılı olduysa geçici grup dosyalarını temizle
        for p in temp_group_files:
            p.unlink(missing_ok=True)

        logger.info("✅ Aylık ERA5-Land dosyası başarıyla oluşturuldu: %s", target_file)
        return target_file
    except Exception as e:
        logger.warning("Ay indirme/birleştirme sırasında hata: %s. İndirilen parçalar korunuyor.", e)
        raise


def download_era5_range(
    years: List[int],
    months: List[int],
    park_id: Optional[str] = None,
    out_dir: Union[str, Path] = "data/raw/era5",
    area: Optional[List[float]] = None,
    client: Optional[Any] = None,
) -> List[Path]:
    """Belirtilen yıl ve ay listesi için ERA5-Land verilerini indirir."""
    check_park_grid_overlap()

    downloaded: List[Path] = []
    for y in sorted(years):
        for m in sorted(months):
            p = download_era5_month(
                year=y,
                month=m,
                out_dir=out_dir,
                area=area,
                client=client,
                max_retries=int(_ERA5_CFG.max_retries.value),
                backoff_seconds=float(_ERA5_CFG.backoff_seconds.value),
            )
            downloaded.append(p)
    return downloaded
