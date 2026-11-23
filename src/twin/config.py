"""Yapılandırma ve parametre kayıt kütüphanesi.

Tüm model, toprak, bitki, asimilasyon ve sensör parametreleri `source` (kaynak)
ve `status` (verified | to_verify | assumption) bilgisiyle tutulur.
"""

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class VerificationStatus(str, Enum):
    """Parametre doğrulama durumu."""

    VERIFIED = "verified"
    TO_VERIFY = "to_verify"
    ASSUMPTION = "assumption"


@dataclass
class ParameterItem:
    """Kaynak ve doğrulama durumunu taşıyan tekil parametre öğesi."""

    value: Any
    unit: str
    source: str
    status: VerificationStatus = VerificationStatus.TO_VERIFY
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "status": self.status.value,
            "description": self.description,
        }


@dataclass
class SoilParameters:
    """Kök bölgesi toprak parametreleri (FAO-56 Bölüm 8)."""

    texture: str = "loam"
    theta_fc: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.28,
            unit="m3/m3",
            source="FAO-56 Table 19 (Medium texture loam soil field capacity)",
            status=VerificationStatus.ASSUMPTION,
            description="Tarla kapasitesi hacimsel su içeriği",
        )
    )
    theta_wp: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.14,
            unit="m3/m3",
            source="FAO-56 Table 19 (Medium texture loam soil wilting point)",
            status=VerificationStatus.ASSUMPTION,
            description="Solma noktası hacimsel su içeriği",
        )
    )
    root_depth_m: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.5,
            unit="m",
            source="FAO-56 (Allen et al. 1998) Table 22, http://www.fao.org/4/x0490e/x0490e0e.htm, Turf grass - cool season: Zr 0.5-1.0 m; lower bound used "
            "(footnote 1: smaller values for irrigation scheduling)",
            status=VerificationStatus.VERIFIED,
            description="Etkili kök bölgesi derinliği (Zr)",
        )
    )
    p_depletion: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.40,
            unit="-",
            source="FAO-56 (Allen et al. 1998) Table 22, http://www.fao.org/4/x0490e/x0490e0e.htm, Turf grass - cool season (p)",
            status=VerificationStatus.VERIFIED,
            description="Kritik tükenme katsayısı (p)",
        )
    )
    runoff_threshold_mm: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=25.0,
            unit="mm",
            source="Urban turf infiltration threshold assumption",
            status=VerificationStatus.ASSUMPTION,
            description="Yüzey akışı yağış eşiği",
        )
    )


@dataclass
class CropParameters:
    """Bitki katsayıları (Kc) ve fenolojik parametreler."""

    veg_type: str = "lawn"
    kc_initial: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.90,
            unit="-",
            source="FAO-56 (Allen et al. 1998) Table 12, http://www.fao.org/4/x0490e/x0490e0b.htm, Turf grass - cool season (Kc ini)",
            status=VerificationStatus.VERIFIED,
            description="Başlangıç dönemi bitki katsayısı (Nisan-Mayıs)",
        )
    )
    kc_mid: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.95,
            unit="-",
            source="FAO-56 (Allen et al. 1998) Table 12, http://www.fao.org/4/x0490e/x0490e0b.htm, Turf grass - cool season (Kc mid)",
            status=VerificationStatus.VERIFIED,
            description="Orta sezon bitki katsayısı (Haziran-Ağustos)",
        )
    )
    kc_end: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.95,
            unit="-",
            source="FAO-56 (Allen et al. 1998) Table 12, http://www.fao.org/4/x0490e/x0490e0b.htm, Turf grass - cool season (Kc end)",
            status=VerificationStatus.VERIFIED,
            description="Sezon sonu bitki katsayısı (Eylül-Ekim)",
        )
    )
    kc_winter: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.60,
            unit="-",
            source="Turfgrass dormant winter Kc assumption",
            status=VerificationStatus.ASSUMPTION,
            description="Kış ve sezon dışı çim Kc katsayısı",
        )
    )
    kc_ndvi_exponent: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=2.0,
            unit="-",
            source="Obriejetan & Krexner (2024), Urban Climate (Kc = NDVI^2, Vienna study assumption)",
            status=VerificationStatus.ASSUMPTION,
            description="NDVI tabanlı deneysel Kc üssü (Türkiye için kalibre edilmeli)",
        )
    )
    kc_ndvi_min: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.20,
            unit="-",
            source="NDVI Kc lower physical bound assumption",
            status=VerificationStatus.ASSUMPTION,
            description="NDVI Kc alt sınırı",
        )
    )
    kc_ndvi_max: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=1.15,
            unit="-",
            source="NDVI Kc upper physical bound assumption",
            status=VerificationStatus.ASSUMPTION,
            description="NDVI Kc üst sınırı",
        )
    )


@dataclass
class IrrigationSystemParameters:
    """Sulama sistemi ve donanım parametreleri."""

    irrigation_type: str = "sprinkler"
    efficiency: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.75,
            unit="-",
            source="FAO Irrigation and Drainage Paper 24 / Standard urban sprinkler efficiency",
            status=VerificationStatus.TO_VERIFY,
            description="Sulama uygulama verimliliği (eta_irr)",
        )
    )
    app_rate_mm_h: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=10.0,
            unit="mm/h",
            source="Typical urban pop-up rotary sprinkler rate (assumed before catch-can test)",
            status=VerificationStatus.ASSUMPTION,
            description="Uygulama debisi hızı (mm/saat)",
        )
    )
    max_pump_s: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=20,
            unit="s",
            source="NodeMCU firmware pump safety rule (INTERFACES.md)",
            status=VerificationStatus.VERIFIED,
            description="Tek seferde izin verilen azami pompa çalışma süresi",
        )
    )
    min_rest_s: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=60,
            unit="s",
            source="NodeMCU firmware pump safety rule (INTERFACES.md)",
            status=VerificationStatus.VERIFIED,
            description="İki pompa çalıştırma arasındaki asgari bekleme süresi",
        )
    )
    s0_interval_days: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=3,
            unit="day",
            source="Fixed schedule S0 irrigation interval assumption",
            status=VerificationStatus.ASSUMPTION,
            description="S0 sabit takvim sulama aralığı (gün)",
        )
    )
    s0_dose_mm: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=12.0,
            unit="mm",
            source="Fixed schedule S0 irrigation dose assumption",
            status=VerificationStatus.ASSUMPTION,
            description="S0 sabit takvim sulama dozu (mm)",
        )
    )
    max_gross_dose_mm: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=35.0,
            unit="mm/day",
            source="Project assumption (CLAUDE.md §3: gross dose upper bound 35 mm)",
            status=VerificationStatus.ASSUMPTION,
            description="Günlük brüt sulama dozu üst sınırı",
        )
    )


@dataclass
class AssimilationParameters:
    """Veri asimilasyonu ve EnKF parametreleri."""

    obs_error_std: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.02,
            unit="m3/m3",
            source="Low-cost capacitive soil sensor measurement standard deviation assumption",
            status=VerificationStatus.ASSUMPTION,
            description="Sensör ölçüm gürültüsü standart sapması (sigma_obs)",
        )
    )
    proc_error_std_dr: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.80,
            unit="mm",
            source="EnKF water balance process noise standard deviation assumption",
            status=VerificationStatus.ASSUMPTION,
            description="EnKF su dengesi kök tükenmesi süreç gürültüsü standart sapması (sigma_proc)",
        )
    )
    nudge_factor: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.35,
            unit="-",
            source="Direct nudging observer gain assumption",
            status=VerificationStatus.ASSUMPTION,
            description="Doğrudan Nudging asimilasyon kazancı (K_nudge)",
        )
    )


@dataclass
class SensorQCParameters:
    """Günlük sensör okumaları için çevrimiçi kalite kontrol eşikleri (sanal park ve ileride saha)."""

    frozen_window_days: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=7,
            unit="gün",
            source=(
                "Koçyiğit vd. (2025) SIMPaCT, arXiv:2508.11700: 120 saatlik pencere (saatlik veride ~120 örnek). "
                "Günlük okumada 5 örnek gürültüyle rastlantısal olarak %1'in altına düşebildiği için 7 örneğe "
                "uzatıldı (varsayım; sağlam sensörde yanlış alarm testte görüldü)"
            ),
            status=VerificationStatus.ASSUMPTION,
            description="Donmuş değer penceresi (günlük okuma sayısı)",
        )
    )
    frozen_max_variation_pct: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=1.0,
            unit="%",
            source="Koçyiğit vd. (2025) SIMPaCT: pencerede değişim < %1 ise takılı sensör",
            status=VerificationStatus.VERIFIED,
            description="Donmuş değer eşiği: (maks - min) / ortalama",
        )
    )
    missing_rate_max: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.50,
            unit="-",
            source="Koçyiğit vd. (2025) SIMPaCT: eksik oranı > %50 ise geçersiz",
            status=VerificationStatus.VERIFIED,
            description="Değerlendirme penceresinde izin verilen en yüksek eksik okuma oranı",
        )
    )
    missing_window_days: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=10,
            unit="gün",
            source="Varsayım: SIMPaCT pencere uzunluğunu günlük okuma için sabitlemez",
            status=VerificationStatus.ASSUMPTION,
            description="Eksik oranının hesaplandığı kayan pencere",
        )
    )
    max_gap_days: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=3,
            unit="gün",
            source="Koçyiğit vd. (2025) SIMPaCT: 3 günü aşan kesinti",
            status=VerificationStatus.VERIFIED,
            description="Art arda bu kadar günden uzun okuma yoksa sensör kesintide sayılır",
        )
    )
    vwc_min: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.0,
            unit="m3/m3",
            source="qc/rules.py fiziksel aralık (VWC 0,0-0,60)",
            status=VerificationStatus.ASSUMPTION,
            description="Fiziksel aralık alt sınırı",
        )
    )
    vwc_max: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.60,
            unit="m3/m3",
            source="qc/rules.py fiziksel aralık (VWC 0,0-0,60)",
            status=VerificationStatus.ASSUMPTION,
            description="Fiziksel aralık üst sınırı",
        )
    )
    above_fc_margin: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.05,
            unit="m3/m3",
            source=(
                "Varsayım: toprak tarla kapasitesinin üstünde günlerce kalamaz (FAO-56 kova modeli fazlayı aynı gün "
                "sızdırır); pay = sanal dünya θFC yayılımı 0,03 + sensör gürültüsü 0,02"
            ),
            status=VerificationStatus.ASSUMPTION,
            description="Okuma nominal θFC + bu payı aşarsa 'tarla kapasitesi üstü' sayılır",
        )
    )
    above_fc_days: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=3,
            unit="gün",
            source="Varsayım: yağış/sulama sonrası kısa süreli doygunluğu ayırmak için art arda gün sayısı",
            status=VerificationStatus.ASSUMPTION,
            description="Tarla kapasitesi üstü okumanın sensörü kalıcı olarak dışlaması için art arda gün sayısı",
        )
    )
    saturation_margin: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.09,
            unit="m3/m3",
            source=(
                "Varsayım: tek okumalık karar için pay = sanal dünya θFC yayılımı 0,03 + 3 × sensör gürültüsü 0,02 "
                "(0,05 payında sağlam sensörde yanlış alarm testte görüldü)"
            ),
            status=VerificationStatus.ASSUMPTION,
            description="Doygunluk sonrası okuma nominal θFC + bu payı aşarsa sensör dışlanır",
        )
    )
    saturation_buffer_mm: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=5.0,
            unit="mm",
            source=(
                "Varsayım: dünkü net su girdisi (yağış + η·sulama) ikizin kestirdiği açığı bu kadar aşarsa kök bölgesi "
                "tarla kapasitesine gelmiş sayılır (doygunluk sonrası referans kontrolü)"
            ),
            status=VerificationStatus.ASSUMPTION,
            description="Doygunluk sonrası referans kontrolü için açık üstü tampon",
        )
    )
    drift_window_days: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=90,
            unit="gün",
            source=(
                "Varsayım: sensör ile sensörü görmeyen açık döngü modeli arasındaki farkın eğimi bu uzunlukta "
                "kayan pencerede EKK ile kestirilir. 60 ve 90 gün, Theil-Sen ve ET ortak değişkenli regresyon "
                "karşılaştırıldı; 90 günlük EKK en iyi ayrımı verdi (docs/model/SENSOR_QC.md §8)"
            ),
            status=VerificationStatus.ASSUMPTION,
            description="Model-sensör tutarlılık (kayma) testi penceresi",
        )
    )
    drift_min_points: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=45,
            unit="okuma",
            source="Varsayım: eğim bu kadar geçerli okumadan önce hesaplanmaz",
            status=VerificationStatus.ASSUMPTION,
            description="Kayma testi için pencerede gereken en az geçerli okuma",
        )
    )
    drift_slope_max: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.0009,
            unit="m3/m3/gün",
            source=(
                "Kalibrasyon: 2020-2021 sanal dünya koşularında sağlam sensörlerin sezon içi en büyük |eğim| "
                "değerlerinin %99'luk dilimi (0,00090); 2022-2024 bağımsız değerlendirme (docs/model/SENSOR_QC.md §8). "
                "Sanal dünyaya özgüdür; sahada yeniden kalibre edilmeli"
            ),
            status=VerificationStatus.ASSUMPTION,
            description="Model-sensör farkının izin verilen en büyük mutlak eğimi (iki yönlü)",
        )
    )


@dataclass
class ERA5Parameters:
    """ECMWF ERA5-Land reanaliz indirme, ızgara ve dönüşüm parametreleri."""

    dataset: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value="reanalysis-era5-land",
            unit="-",
            source="Copernicus Climate Data Store (CDS) Catalogue",
            status=VerificationStatus.VERIFIED,
            description="ERA5-Land saatlik reanaliz veri seti tanımlayıcısı",
        )
    )
    area_north: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=41.10,
            unit="deg_N",
            source="İstanbul Beşiktaş park alanlarını kapsayan koordinat sınırı",
            status=VerificationStatus.ASSUMPTION,
            description="Kuzey enlem sınırı",
        )
    )
    area_west: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=28.90,
            unit="deg_E",
            source="İstanbul Beşiktaş park alanlarını kapsayan koordinat sınırı",
            status=VerificationStatus.ASSUMPTION,
            description="Batı boylam sınırı",
        )
    )
    area_south: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=41.00,
            unit="deg_N",
            source="İstanbul Beşiktaş park alanlarını kapsayan koordinat sınırı",
            status=VerificationStatus.ASSUMPTION,
            description="Güney enlem sınırı",
        )
    )
    area_east: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=29.10,
            unit="deg_E",
            source="İstanbul Beşiktaş park alanlarını kapsayan koordinat sınırı",
            status=VerificationStatus.ASSUMPTION,
            description="Doğu boylam sınırı",
        )
    )
    grid_resolution_deg: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.10,
            unit="deg",
            source="ECMWF ERA5-Land native horizontal resolution specification (~9 km)",
            status=VerificationStatus.VERIFIED,
            description="ERA5-Land ızgara çözünürlüğü (derece)",
        )
    )
    yildiz_lat: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=41.0484,
            unit="deg_N",
            source="İBB Açık Veri Portalı Park Poligonu / Beşiktaş Envanteri",
            status=VerificationStatus.ASSUMPTION,
            description="Yıldız Parkı enlem koordinatı",
        )
    )
    yildiz_lon: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=29.0159,
            unit="deg_E",
            source="İBB Açık Veri Portalı Park Poligonu / Beşiktaş Envanteri",
            status=VerificationStatus.ASSUMPTION,
            description="Yıldız Parkı boylam koordinatı",
        )
    )
    macka_lat: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=41.0443,
            unit="deg_N",
            source="İBB Açık Veri Portalı Park Poligonu / Beşiktaş Envanteri",
            status=VerificationStatus.ASSUMPTION,
            description="Maçka Demokrasi Parkı enlem koordinatı",
        )
    )
    macka_lon: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=28.9931,
            unit="deg_E",
            source="İBB Açık Veri Portalı Park Poligonu / Beşiktaş Envanteri",
            status=VerificationStatus.ASSUMPTION,
            description="Maçka Demokrasi Parkı boylam koordinatı",
        )
    )
    kelvin_offset: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=273.15,
            unit="K",
            source="SI Standard (ISO 80000-5)",
            status=VerificationStatus.VERIFIED,
            description="Kelvin-Santigrat sıcaklık dönüşüm ofseti",
        )
    )
    wind_height_factor: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.7480,
            unit="-",
            source="FAO-56 Eq. 47 (4.87 / ln(67.8 * 10 - 5.42))",
            status=VerificationStatus.VERIFIED,
            description="10m'den 2m standart yüksekliğe rüzgâr hızı indirgeme faktörü",
        )
    )
    max_retries: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=3,
            unit="count",
            source="Copernicus CDS API indirme hata dayanımı politikası",
            status=VerificationStatus.VERIFIED,
            description="İndirme isteklerinde azami tekrar deneme sayısı",
        )
    )
    backoff_seconds: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=5.0,
            unit="s",
            source="API retry exponential backoff base",
            status=VerificationStatus.VERIFIED,
            description="Üstel bekleme taban süresi",
        )
    )
    raw_data_dir: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value="data/raw/era5",
            unit="path",
            source="Proje dosya organizasyonu standartları",
            status=VerificationStatus.VERIFIED,
            description="Ham ERA5 NetCDF dosyalarının saklandığı dizin",
        )
    )


@dataclass
class DeviceParameters:
    """Sensör düğümü platformu: raporlama, ham okuma kalibrasyonu ve uyarı eşikleri (sanal ve gerçek düğüm)."""

    report_interval_s: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=900,
            unit="s",
            source="Varsayım: düğüm 15 dakikada bir okur ve yayınlar (firmware ölçüm aralığıyla uyumlu tutulmalı)",
            status=VerificationStatus.ASSUMPTION,
            description="Telemetri aralığı",
        )
    )
    soil_raw_dry: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=1000,
            unit="ADC",
            source="firmware/sulama_node/config.example.h SOIL_RAW_DRY (kuru hava referansı; kalibrasyon yapılmadı)",
            status=VerificationStatus.ASSUMPTION,
            description="Kapasitif sensör ham değeri: kuru",
        )
    )
    soil_raw_wet: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=400,
            unit="ADC",
            source="firmware/sulama_node/config.example.h SOIL_RAW_WET (su referansı; kalibrasyon yapılmadı)",
            status=VerificationStatus.ASSUMPTION,
            description="Kapasitif sensör ham değeri: su",
        )
    )
    vwc_full_scale: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.40,
            unit="m3/m3",
            source="firmware rawToVWC(): CALIB_SLOPE yoksa (kuru - ham)/(kuru - ıslak) · 0,40",
            status=VerificationStatus.ASSUMPTION,
            description="Ham okumanın doğrusal VWC karşılığında ıslak uç",
        )
    )
    offline_after_intervals: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=3,
            unit="aralık",
            source="Varsayım: art arda 3 rapor gelmezse düğüm çevrimdışı sayılır",
            status=VerificationStatus.ASSUMPTION,
            description="Çevrimdışı uyarısı eşiği",
        )
    )
    battery_low_v: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=3.4,
            unit="V",
            source="Varsayım: tek hücre Li-ion için düşük pil uyarısı (üretici eğrisiyle doğrulanmalı)",
            status=VerificationStatus.ASSUMPTION,
            description="Düşük pil uyarısı",
        )
    )
    rssi_weak_dbm: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=-85,
            unit="dBm",
            source="Varsayım: Wi-Fi için zayıf sinyal eşiği",
            status=VerificationStatus.ASSUMPTION,
            description="Zayıf sinyal uyarısı",
        )
    )
    sim_battery_drain_v_per_day: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.004,
            unit="V/gün",
            source="Sanal düğüm varsayımı (pil boşalması; gerçek düğümde ölçülecek)",
            status=VerificationStatus.ASSUMPTION,
            description="Simülatör: günlük pil gerilimi düşüşü",
        )
    )
    sim_short_noise_vwc: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.003,
            unit="m3/m3",
            source=(
                "Sanal düğüm varsayımı: 15 dakikalık okumalar arası kısa dönem gürültü. Günlük hata (gürültü, kayma, "
                "donma, veri kaybı) sanal dünyadaki sensör modelinden günde bir kez çekilir"
            ),
            status=VerificationStatus.ASSUMPTION,
            description="Simülatör: gün içi okuma gürültüsü",
        )
    )
    alert_hysteresis_db: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=3,
            unit="dB",
            source="Varsayım: zayıf sinyal uyarısı eşik + 3 dB'ye dönünce kapanır (uyarı çırpınmasını önler)",
            status=VerificationStatus.ASSUMPTION,
            description="Sinyal uyarısı kapanma payı",
        )
    )
    alert_hysteresis_v: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.05,
            unit="V",
            source="Varsayım: düşük pil uyarısı eşik + 0,05 V'a dönünce kapanır",
            status=VerificationStatus.ASSUMPTION,
            description="Pil uyarısı kapanma payı",
        )
    )
    sim_irrigation_hour: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=5,
            unit="saat",
            source="Sanal park varsayımı: ikizin önerdiği sulama sabah 05:00'te sanal sisteme uygulanır",
            status=VerificationStatus.ASSUMPTION,
            description="Simülatör: sulama saati",
        )
    )


@dataclass
class TwinConfig:
    """Tüm dijital ikiz yapılandırma kümesi."""

    soil: SoilParameters = field(default_factory=SoilParameters)
    crop: CropParameters = field(default_factory=CropParameters)
    irrigation: IrrigationSystemParameters = field(default_factory=IrrigationSystemParameters)
    assimilation: AssimilationParameters = field(default_factory=AssimilationParameters)
    sensor_qc: SensorQCParameters = field(default_factory=SensorQCParameters)
    devices: DeviceParameters = field(default_factory=DeviceParameters)
    era5: ERA5Parameters = field(default_factory=ERA5Parameters)
    irrigated_fraction: ParameterItem = field(
        default_factory=lambda: ParameterItem(
            value=0.60,
            unit="-",
            source="Park total area to irrigated green turf fraction assumption (DATA_INVENTORY.md)",
            status=VerificationStatus.ASSUMPTION,
            description="Park poligonu içindeki sulanan yeşil alan oranı varsayımı",
        )
    )

    def to_dict(self) -> Dict[str, Any]:
        """Tüm yapılandırmayı sözlük olarak serileştirir."""
        return {
            "soil": {
                k: getattr(self.soil, k).to_dict()
                if hasattr(getattr(self.soil, k), "to_dict")
                else getattr(self.soil, k)
                for k in self.soil.__dataclass_fields__
            },
            "crop": {
                k: getattr(self.crop, k).to_dict()
                if hasattr(getattr(self.crop, k), "to_dict")
                else getattr(self.crop, k)
                for k in self.crop.__dataclass_fields__
            },
            "irrigation": {
                k: getattr(self.irrigation, k).to_dict()
                if hasattr(getattr(self.irrigation, k), "to_dict")
                else getattr(self.irrigation, k)
                for k in self.irrigation.__dataclass_fields__
            },
            "devices": {k: getattr(self.devices, k).to_dict() for k in self.devices.__dataclass_fields__},
            "sensor_qc": {
                k: getattr(self.sensor_qc, k).to_dict() for k in self.sensor_qc.__dataclass_fields__
            },
            "assimilation": {
                k: getattr(self.assimilation, k).to_dict()
                if hasattr(getattr(self.assimilation, k), "to_dict")
                else getattr(self.assimilation, k)
                for k in self.assimilation.__dataclass_fields__
            },
            "era5": {
                k: getattr(self.era5, k).to_dict()
                if hasattr(getattr(self.era5, k), "to_dict")
                else getattr(self.era5, k)
                for k in self.era5.__dataclass_fields__
            },
            "irrigated_fraction": self.irrigated_fraction.to_dict(),
        }


# ==============================================================================
# BİTKİ TİPİ PROFİLLERİ
# Yalnızca birincil kaynaktan doğrulanmış değerler girilir. Kaynağı doğrulanmamış bir bitki
# tipi (ağaç, çalı, mevsimlik çiçek) buraya EKLENMEZ; config_for_vegetation() KeyError verir.
# ==============================================================================

FAO56_TABLE12 = "FAO-56 (Allen et al. 1998) Table 12, http://www.fao.org/4/x0490e/x0490e0b.htm"
FAO56_TABLE22 = "FAO-56 (Allen et al. 1998) Table 22, http://www.fao.org/4/x0490e/x0490e0e.htm"


@dataclass
class VegetationProfile:
    """Bir bitki tipinin su dengesi parametreleri (Kc evreleri, kök derinliği, p)."""

    name: str
    kc_initial: ParameterItem
    kc_mid: ParameterItem
    kc_end: ParameterItem
    root_depth_m: ParameterItem
    p_depletion: ParameterItem


def _fao_turf_profile(name: str, label: str, kc: tuple, p: float) -> VegetationProfile:
    def item(value, unit, source, desc):
        return ParameterItem(value, unit, source, VerificationStatus.VERIFIED, desc)

    return VegetationProfile(
        name=name,
        kc_initial=item(kc[0], "-", f"{FAO56_TABLE12}, Turf grass - {label} (Kc ini)", "Kc ini"),
        kc_mid=item(kc[1], "-", f"{FAO56_TABLE12}, Turf grass - {label} (Kc mid)", "Kc mid"),
        kc_end=item(kc[2], "-", f"{FAO56_TABLE12}, Turf grass - {label} (Kc end)", "Kc end"),
        root_depth_m=item(
            0.5,
            "m",
            f"{FAO56_TABLE22}, Turf grass - {label}: Zr 0.5-1.0 m; lower bound used "
            "(footnote 1: smaller values for irrigation scheduling)",
            "Etkili kök derinliği (aralığın alt sınırı)",
        ),
        p_depletion=item(p, "-", f"{FAO56_TABLE22}, Turf grass - {label} (p)", "Stressiz tükenme kesri"),
    )


VEGETATION_PROFILES: Dict[str, VegetationProfile] = {
    # Lolium perenne + Festuca arundinacea karışımı serin iklim çimidir (FAO-56 Tablo 12, dipnot 15).
    "turf_cool_season": _fao_turf_profile("turf_cool_season", "cool season", (0.90, 0.95, 0.95), 0.40),
    "turf_warm_season": _fao_turf_profile("turf_warm_season", "warm season", (0.80, 0.85, 0.85), 0.50),
}

# parks.py zon tipleri -> profil eşlemesi (yalnız doğrulanmış profili olanlar)
ZONE_VEG_TYPE_TO_PROFILE: Dict[str, str] = {"lawn": "turf_cool_season"}


def config_for_vegetation(profile_key: str, base: Optional["TwinConfig"] = None) -> "TwinConfig":
    """Temel yapılandırmanın kopyasına bitki profilinin Kc, Zr ve p değerlerini yazar.

    Toprak (θFC, θWP), sulama verimi ve diğer parametreler temel yapılandırmadan gelir.
    """
    if profile_key not in VEGETATION_PROFILES:
        raise KeyError(
            f"'{profile_key}' için kaynağı doğrulanmış bitki profili yok. "
            f"Mevcut: {sorted(VEGETATION_PROFILES)}"
        )
    prof = VEGETATION_PROFILES[profile_key]
    cfg = copy.deepcopy(base or TwinConfig())
    cfg.crop.veg_type = prof.name
    cfg.crop.kc_initial = prof.kc_initial
    cfg.crop.kc_mid = prof.kc_mid
    cfg.crop.kc_end = prof.kc_end
    cfg.soil.root_depth_m = prof.root_depth_m
    cfg.soil.p_depletion = prof.p_depletion
    return cfg


DEFAULT_CONFIG = TwinConfig()
