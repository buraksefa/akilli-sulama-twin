# Açık Sorular ve Belirsizlikler (OPEN_QUESTIONS.md)

Bu belge, yüksek lisans tez çalışmasında danışman hoca (Prof. Dr. Gülfem Alptekin) ve kurumlarla (İBB Park ve Bahçeler Dairesi, İSKİ) netleştirilmesi gereken açık soruları ve kod tabanında kullanılan varsayılan kararları içerir.

---

## 1. Danışmana ve Kurumlara Sorulacak Sorular

1. **Sulama Bölgeleri (Zones) ve Vana Sayıları:**
   - Yıldız Korusu ve Maçka Parkı'nda vana başına düşen sulama alt bölgeleri kaç adettir?
   - *Mevcut varsayılan:* Her park için tek varsayılan bölge ve toplam poligon alanının %60'ının sulandığı varsayımı (`irrigated_fraction = 0.60`).
2. **Toprak Türü ve Laboratuvar Analizi:**
   - Yıldız ve Maçka parklarından alınacak toprak numuneleri laboratuvarda bünye (tekstür), tarla kapasitesi ve solma noktası analizine tabi tutulacak mı?
   - *Mevcut varsayılan:* FAO-56 Tablo 19 tınlı toprak parametreleri ($\theta_{FC}=0.28$, $\theta_{WP}=0.14$, $Z_r=0.30\text{ m}$, $p=0.50$, `status: assumption`).
3. **Mevcut Sulama Programı ve Otomasyon:**
   - Parklarda sulama şu an sabit zamanlayıcı (örneğin haftada 3 gece) ile mi, yoksa işçi inisiyatifiyle mi yapılıyor? Sayaçlar akıllı mı yoksa aylık mekanik okuma mı?
   - *Mevcut varsayılan:* S0 Sabit takvim (3 günde bir 12 mm).
4. **Çim Türü ve Kc Katsayıları:**
   - Parklarda kullanılan çim serin iklim (Festuca/Poa) mi yoksa sıcak iklim karışımı mı?
   - *Mevcut varsayılan:* FAO-56 Tablo 12 serin iklim çimi ($K_{c,ini}=0.85$, $K_{c,mid}=0.95$, $K_{c,end}=0.85$, `status: to_verify`).
5. **NDVI Ağaç Tacı Maskesi:**
   - Yıldız Korusu yoğun ağaçlıklı olduğu için 10m Sentinel-2 NDVI pikseli ağaç tacını ölçmektedir. Sulanan çim alanlarını izole etmek için İBB Coğrafi Bilgi Sistemi'nden çim katmanı poligonu talep edilecek mi?
6. **ERA5-Land Izgara Çözünürlüğü ve Mikro-İklim Temsiliyeti:**
   - ERA5-Land reanaliz ızgarası 0.1° (~9 km) olup, Beşiktaş'taki Yıldız Korusu ve Maçka Demokrasi Parkı aynı ızgara hücresine düşmektedir. Yıldız'ın yoğun koru/ağaç mikrokliması ile Maçka'nın açık vadi rüzgâr profili arasındaki yerel farklar yalnızca saha IoT sensörleri ve veri asimilasyonu (EnKF) ile kapatılabilir mi?
7. **Copernicus CDS Nokta Tabanlı Zaman Serisi Erişimi (`reanalysis-era5-land-timeseries`):**
   - Copernicus CDS API kataloğunda nokta koordinatı bazlı doğrudan çok yıllık zaman serisi indiren standart bir `reanalysis-era5-land-timeseries` API uç noktası resmi olarak mevcut mudur, yoksa `reanalysis-era5-land` üzerinde alan kutusu (`area`) ile alt kümeleme yapılması tek resmi yöntem midir?

---

## 2. Kod Tabanındaki Varsayılan Değerler Özeti

| Parametre | Varsayılan Değer | Durum | Gerekçe |
| --- | --- | --- | --- |
| `soil.theta_fc` | 0.28 m³/m³ | assumption | Tınlı toprak tarla kapasitesi |
| `soil.theta_wp` | 0.14 m³/m³ | assumption | Tınlı toprak solma noktası |
| `soil.root_depth_m` | 0.30 m | assumption | Kent çimi ortalama kök derinliği |
| `soil.p_depletion` | 0.50 | to_verify | FAO-56 çim tükenme kesri |
| `soil.runoff_threshold_mm` | 25.0 mm | assumption | Yüzey akışı tetiklenme eşiği |
| `crop.kc_winter` | 0.60 | assumption | Kış dönemi baz çim Kc katsayısı |
| `crop.kc_ndvi_exponent` | 2.0 | assumption | Viyana çalışması ($Kc = NDVI^2$) |
| `crop.kc_ndvi_min` | 0.20 | assumption | NDVI tabanlı Kc alt sınırı |
| `crop.kc_ndvi_max` | 1.15 | assumption | NDVI tabanlı Kc üst sınırı |
| `assimilation.obs_error_std` | 0.02 m³/m³ | assumption | Kapasitif sensör ölçüm gürültüsü |
| `assimilation.proc_error_std_dr` | 0.80 mm | assumption | Kök bölgesi model süreç gürültüsü |
| `irrigation.s0_interval_days` | 3 gün | assumption | Sabit takvim sulama periyodu |
| `irrigation.s0_dose_mm` | 12.0 mm | assumption | Sabit takvim tek seferlik brüt doz |
| `irrigation.efficiency` | 0.75 | to_verify | Standart kentsel fıskiye verimi |
| `irrigation.max_pump_s` | 20 sn | verified | Donanım güvenlik kuralı |
| `irrigation.min_rest_s` | 60 sn | verified | Donanım güvenlik kuralı |
| `irrigated_fraction` | 0.60 | assumption | Park poligonundan sulanan alana geçiş |
| `era5.dataset` | reanalysis-era5-land | verified | Copernicus Climate Data Store |
| `era5.grid_resolution_deg` | 0.10° (~9 km) | verified | ECMWF ERA5-Land native resolution |
| `era5.wind_height_factor` | 0.7480 | verified | FAO-56 Denklem 47 (10m -> 2m) |
| `era5.kelvin_offset` | 273.15 K | verified | SI Standardı (T_C = T_K - 273.15) |
