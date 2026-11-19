# Veri envanteri ve giriş sözleşmeleri

Durum: **hazır** (elimizde), **bekliyor** (talep edildi), **planlı** (henüz talep yok).
Bekleyen veriler gelene kadar kod, aşağıdaki şemalara uyan **sentetik** dosyalarla geliştirilir.

## Kaynaklar

| Veri | Kaynak | Durum | Not |
| --- | --- | --- | --- |
| Saatlik hava, toprak nemi katmanları | ERA5-Land (Copernicus CDS), 0,1° | hazır (indirme kodu var) | Birikimli değişkenler: saatlik değere çevir. Parkları ayırt etmez |
| Park poligonları | `data/public/parks.geojson` (İBB, 2025-04-08) | hazır | Yıldız Korusu 389.760 m², Maçka 139.419 m². Poligon alanı sulanan alan değildir |
| Yıllık yeşil alan suyu | `data/public/ibb_green_area_water_by_year.csv` (İBB, 2026-03-04) | hazır | 2017–2025, kapsam belirsiz (refüjler dahil olabilir) |
| NDVI (Sentinel-2) | Copernicus Data Space | planlı | Ağaç tacı etkisi; çim maskesi gerekir |
| Sulama bölgeleri, hat/vana, yöntem, program, kaynak, kontrol | İBB Park ve Bahçeler | bekliyor | Talep gönderildi (Ekim 2026) |
| Park bazlı sayaç, tüketim | İSKİ ve/veya İBB | bekliyor | İSKİ görüşmesi 20 Ekim 2026. **Gizli, repoya girmez** |
| Yerel meteoroloji gözlemi | MGM veya İBB istasyonu | planlı | Talep ve erişim doğrulanmadı |
| Testbed telemetrisi | NodeMCU, MQTT, InfluxDB | planlı | Kış verisi; yaz dinamiği taşımaz |
| Referans toprak nemi (gravimetrik) | Kendi ölçümüm | planlı | Kalibrasyon ve doğrulama için |

## Giriş sözleşmeleri (kurum verisi gelince bu şemaya dönüştürülür)

Sütun adları İngilizce, birimler sütun adında. Boş değer = bilinmiyor. Hepsi UTF-8, ISO 8601 zaman
(Europe/Istanbul veya `Z`).

**`zones.geojson`** (poligon, EPSG:4326)

| Alan | Tür | Açıklama |
| --- | --- | --- |
| `zone_id` | str | Benzersiz |
| `park_id` | str | `yildiz`, `macka` |
| `veg_type` | enum | `lawn`, `meadow`, `flower`, `shrub`, `tree`, `mixed` |
| `irrigation_type` | enum | `sprinkler`, `drip`, `none` |
| `area_m2` | float | Sulanan alan |
| `app_rate_mm_h` | float | Uygulama oranı (kap testi varsa) |
| `valve_id`, `controller_id` | str | Varsa |
| `water_source` | enum | `network`, `well`, `reclaimed`, `tank`, `unknown` |

**`soil_params.csv`:** `zone_id, texture, theta_fc, theta_wp, root_depth_m, p_depletion, source, status`

**`schedule.csv`:** `zone_id, season_start, season_end, weekdays (örn. 1010100), start_time, duration_min`

**`irrigation_log.csv`:** `timestamp, zone_id, runtime_min`

**`meter_readings.csv`:** `meter_id, park_id, timestamp, volume_m3, kind (cumulative|increment), resolution_min`

**`station_obs.csv`:** `timestamp, station_id, t_c, rh_pct, wind_ms, rain_mm, rad_wm2`

**Testbed (InfluxDB, mevcut):** measurement `sulama`, etiket `node`, alanlar `soil_raw, soil_pct, temp_c,
hum_pct, pump_s, rssi, seq, err`. Çok kanallı sensörle `soil_raw_1`, `soil_raw_2` eklenecek.

## Kurallar

1. Kurum verisi (İSKİ, İBB Park ve Bahçeler) geldiğinde sunucudaki şifreli dizinde tutulur, repoya girmez.
2. Poligon alanını sulanan alan yerine kullanmak zorunda kalınırsa `irrigated_fraction` varsayımı yapılandırmada
   açıkça yazılır ve sonuçlara dipnot düşülür.
3. Her yeni veri için: kaynak, tarih, lisans, kapsam ve bilinen sınırlılık bu dosyaya eklenir.
