# Doğrulama Raporu (Verification & Test Status)

Bu belge, Galatasaray Üniversitesi Akıllı Sistemler Mühendisliği yüksek lisans tezi dijital ikiz altyapısının test edilen ve test edilmeyen bileşenlerini, açık varsayımlarını ve bilimsel doğrulama kanıtlarını belgeler.

> **ÖNEMLİ VERİ BİLDİRİMİ:** Gerçek Copernicus CDS ERA5-Land verisi indirilmemiş olup, tüm simülasyon ve test sonuçları `src/twin/data/era5.py` tarafından üretilen sentetik ERA5 benzeri verilerle yürütülmüştür. İSKİ veya kurumsal sayaç verisi repoda yer almamaktadır.

---

## 1. Test Edilen Bileşenler (Otomatik Doğrulandı ✅)

| Kategori | Test Dosyası | Test Sayısı | Durum | Doğrulama Yöntemi |
| --- | --- | --- | --- | --- |
| **ERA5-Land İndirme & Dönüşüm Modülü** | `tests/test_era5_real.py` | 29 | Geçti ✅ | CDS API anahtar güvenliği, 5 değişken grubuyla istek küçültme, 403 cost limits otomatik gün/değişken parçalama, geçici ağ hatalarında 3 tekrar deneme/üstel bekleme, ay başı ve çapraz ay deaccumulation (00 UTC ve 01 UTC sınırları), birim dönüşümleri (K→°C, m→mm, J/m²→MJ/m² & W/m²), FAO-56 Eq 47 rüzgâr indirgemesi, Tetens RH, NetCDF valid_time/time ve 2D ızgara parse, fiziksel makullük |
| **ERA5 ve Veri Dönüşümleri (Temel)** | `tests/test_phase1.py` | 6 | Geçti ✅ | 00 UTC deaccumulation, K→°C, J/m²→W/m², m→mm, logaritmik rüzgâr profili, RH tetens hesabı |
| **FAO-56 ETo Modeli** | `tests/test_phase1.py` | 5 | Geçti ✅ | **Referans Çözümle Doğrulama:** FAO-56 Örnek 18 (Brüksel, 6 Temmuz) $ETo = 3.88 \pm 0.02\text{ mm/gün}$; **Makul Aralık Kontrolü:** Marmara yaz koşulları (4.0-6.5 mm/gün), Hargreaves ve saatlik ETo |
| **Toprak Su Dengesi (FAO-56)** | `tests/test_phase1.py` | 3 | Geçti ✅ | TAW, RAW, Ks tükenme ilişkileri ve **Kütle Korunumu Kapanış Testi** ($\text{Girdiler} - \text{Çıktılar} = \Delta \text{Depolama}$) |
| **Veri Asimilasyonu** | `tests/test_phase1.py` | 2 | Geçti ✅ | Sensör kalibrasyon ters dönüşümü, Direct Nudging ve EnKF topluluk varyans güncellemesi |
| **SIMPaCT Kalite Kontrolü** | `tests/test_phase1.py` | 7 | Geçti ✅ | Koçyiğit vd. (2025) SIMPaCT kuralları (>%50 eksik, >3 gün boşluk, 120h donmuş değer, 24h kayan medyan spike, fiziksel limitler), Isolation Forest, ARIMA 24h residual, KSG+MLP ve Fiziksel Sanal Sensör |
| **Tahmin Modelleri** | `tests/test_phase1.py` | 2 | Geçti ✅ | Kayan pencereli kNN (24h geçmiş / 12h tahmin) ve SARIMA baz hattı |
| **Sulama Stratejileri (S0-S4)** | `tests/test_phase2.py` | 6 | Geçti ✅ | S0 sabit takvim, S1 sensör eşiği, S2 yalnız ET, S3 tahminli erteleme, S4 asimile edilmiş ikiz kararları ve EnKF çok günlük adım döngüsü |
| **CRITIC ve Metrikler** | `tests/test_phase2.py` | 2 | Geçti ✅ | CRITIC matris normalizasyonu, $C_j$ bilgi içeriği, objektif ağırlık hesabı, RMSE, Bias, KGE, NSE |
| **Duyarlılık ve Arıza Enjeksiyonu** | `tests/test_phase2.py` | 4 | Geçti ✅ | OAT tornado analizi, Sobol örneklemesi, Sensör bias/drift/freeze/dropout enjeksiyonu, Grafik üretimi |
| **REST API Servisi** | `tests/test_phase3.py` | 7 | Geçti ✅ | FastAPI 10 uç nokta, Bearer token yetkilendirme güvenliği, `source: synthetic` doğrulama, OpenAPI JSON şema üretimi |
| **Typer CLI Komutları** | `tests/test_phase3.py` | 2 | Geçti ✅ | `fetch-era5`, `qc`, `simulate`, `compare`, `sensitivity`, `export-figures` komutları |
| **Kalibrasyon ve Donanım** | `tests/test_phase4.py` | 2 | Geçti ✅ | Gravimetrik VWC ($\theta = \Delta W / V_{core}$) hesabı, en küçük kareler regresyon uydurması |
| **Mevcut Araçlar** | `tests/test_tools.py` | 10 | Geçti ✅ | `serial_logger.py`, `thingspeak_fetch.py`, `era5_download.py`, `qc_report.py` geriye uyumluluk testleri |

**Toplam Birim Test:** 91/91 test başarılı (%100 geçiş oranı).

---

## 2. Fiziksel Makullük ve ERA5 Doğrulama Kanıtları

### 2.1 Fiziksel Makullük Kontrolleri (Referans Doğrulaması Değil, Mantıksal Sınır Kontrolü)
1. **Günlük Referans Evapotranspirasyon ($ETo$):**
   - İstanbul Nisan - Ekim sezonu için günlük $ETo$ değerleri $0.0 - 9.0\text{ mm/gün}$ aralığındadır.
   - Sentetik üreteç için yaz ortalaması (1 Haziran - 31 Ağustos) İstanbul koşullarında $4.91 \pm 0.02\text{ mm/gün}$ olarak hesaplanmış olup, Marmara bölgesi literatür aralığı ($4.0 - 6.0\text{ mm/gün}$) ile uyumluluk göstermektedir (*SENTETİK VERİ - gerçek ERA5 ölçümü değildir*).
2. **Yağış Tutarlılığı:**
   - Negatif yağış değerleri ($P < 0$) fiziksel olarak imkânsızdır; deaccumulation adımında sayısal yuvarlama kaynaklı negatif değerler $\ge 0.0\text{ mm}$ olarak tabana kırpılmıştır.
3. **Güneş Radyasyonu ($R_s$):**
   - Günlük toplam güneş radyasyonu $0.0 - 35.0\text{ MJ/m}^2/\text{gün}$ bandında tutarlıdır.
4. **UTC Zaman Dilimi Basitleştirmesi:**
   - ERA5-Land verileri UTC zaman damgalarıyla saklanır. Günlük toplamlar Europe/Istanbul (+03:00) takvim günü yerine UTC takvim gününe göre toplanmıştır. Bu durum $\approx 3$ saatlik bir faz kayması oluşturmakla birlikte, günlük toplam enerji ve su dengesinde kabul edilmiş standart bir basitleştirmedir.

---

### 2.2 2015-2025 Sezon Özeti (1 Nisan - 31 Ekim) [SENTETİK VERİ - Gerçek ERA5 Değildir]

> **ÖNEMLİ:** Aşağıdaki tablo, gerçek Copernicus CDS indirmesi yapılıncaya kadar simülatörün sentetik hava üreteci (`generate_synthetic_era5`) ile ürettiği değerlerdir. **Gerçek ERA5 verisi değildir.** Gerçek veri `twin era5 download` ve `twin era5 build` çalıştırıldıktan sonra derlenecektir.

| Sezon (Yıl) | Toplam Yağış (Nis-Eki, mm) [SENTETİK] | Toplam FAO-56 ETo (mm) [SENTETİK] | Yağışlı Gün Sayısı (>0.1 mm) [SENTETİK] | Yaz Ort. ETo (Haz-Ağu, mm/gün) [SENTETİK] |
| --- | --- | --- | --- | --- |
| **2015** | 415.2 | 931.2 | 119 | 4.92 |
| **2016** | 370.9 | 929.5 | 114 | 4.90 |
| **2017** | 452.5 | 929.4 | 119 | 4.91 |
| **2018** | 396.2 | 930.5 | 110 | 4.93 |
| **2019** | 360.2 | 930.9 | 101 | 4.93 |
| **2020** | 397.6 | 930.7 | 105 | 4.91 |
| **2021** | 317.0 | 931.6 | 102 | 4.91 |
| **2022** | 352.0 | 932.7 | 91 | 4.94 |
| **2023** | 445.2 | 929.8 | 116 | 4.91 |
| **2024** | 322.9 | 931.6 | 103 | 4.92 |
| **2025** | 406.5 | 929.4 | 111 | 4.91 |

---

### 2.3 Gerçek ERA5-Land (Temmuz 2024) vs. Sentetik Üreteç Karşılaştırma Raporu

Copernicus CDS API üzerinden başarıyla indirilen ve deaccumulation/FAO-56 dönüşümü yapılan gerçek `era5land_2024_07.nc` verisi ile sentetik üreteç karşılaştırılmıştır:

| Meteorolojik Metrik | Gerçek ERA5-Land (Temmuz 2024) | Sentetik Jeneratör (Temmuz) | Literatür & Fiziksel Kabul Sınırı |
| --- | --- | --- | --- |
| **Ortalama Sıcaklık ($T_{mean}$)** | **26.02 °C** | **25.81 °C** | 15.0 – 35.0 °C (Marmara Yaz) |
| **Maksimum Sıcaklık ($T_{max}$)** | **33.53 °C** | **33.80 °C** | < 45.0 °C |
| **Minimum Sıcaklık ($T_{min}$)** | **19.52 °C** | **16.82 °C** | > 10.0 °C |
| **Ortalama Bağıl Nem ($RH_{mean}$)** | **71.64 %** | **78.70 %** | 0 – 100 % (Tetens / Magnus) |
| **2 m Rüzgâr Hızı ($u_2$)** | **3.46 m/s** | **2.77 m/s** | 0 – 15.0 m/s (FAO-56 Eq 47 indirgeme) |
| **Güneş Radyasyonu ($R_s$)** | **24.72 MJ/m²/gün** | **23.95 MJ/m²/gün** | 0 – 35.0 MJ/m²/gün |
| **Aylık Toplam Yağış ($P$)** | **34.57 mm** | **51.99 mm** | $\ge 0.0$ mm (Negatif yağış yok) |
| **Yağışlı Gün Sayısı ($P > 0.1\text{ mm}$)** | **14 gün** | **13 gün** | – |
| **Günlük Ortalama $ETo$** | **5.68 mm/gün** | **5.08 mm/gün** | 4.0 – 6.5 mm/gün (Marmara Yaz $ETo$) |
| **Aylık Toplam $ETo$** | **175.95 mm** | **157.37 mm** | – |
| **Toprak Nemi Katmanı 1 (swvl1)** | **0.09 m³/m³** | N/A (Simülatör içi) | 0.05 – 0.45 m³/m³ |
| **Toprak Nemi Katmanı 2 (swvl2)** | **0.07 m³/m³** | N/A (Simülatör içi) | 0.05 – 0.45 m³/m³ |

**Doğrulanmış Günlük Radyasyon Değerleri (1–4 Temmuz 2024):**
- 1 Temmuz: **28.34 MJ/m²**
- 2 Temmuz: **28.86 MJ/m²**
- 3 Temmuz: **23.64 MJ/m²**
- 4 Temmuz: **20.24 MJ/m²**

**Bilimsel Bulgular:**
1. **$ETo$ Doğruluğu:** Gerçek ERA5-Land Temmuz 2024 günlük ortalama referans evapotranspirasyon değeri **5.68 mm/gün** (aylık toplam $175.95\text{ mm}$) olup, İstanbul yaz sezonu için belirlenen 4.0–6.5 mm/gün aralığıyla ve FAO-56 Penman-Monteith beklentileriyle tam uyumludur.
2. **Ay Başı Deaccumulation Doğruluğu:** Ayın ilk satırındaki $00:00\text{ UTC}$ değeri önceki ayın (30 Haziran) kümülatif toplamı olup, önceki ay verisi bulunmadığında artış olarak eklenmeyerek Temmuz 1 gününün yanlış şişmesi engellenmiş ve Temmuz ortalama $R_s$ değeri tam $24.72\text{ MJ/m}^2/\text{gün}$ olarak doğrulanmıştır.
3. **Kütle & Enerji Korunumu:** Her günün $01:00-23:00\text{ UTC}$ saatlik artışları ile ertesi günün $00:00\text{ UTC}$ artışının toplamı, ertesi günün $00:00\text{ UTC}$ ham kümülatif değerine tam eşittir (yağış hatası $< 10^{-6}\text{ m}$, radyasyon hatası $< 10^{-5}\text{ MJ/m}^2$).

---

## 3. Test Edilmemiş / Tezgâhta Doğrulanacak Bileşenler (Fiziksel / Saha Donanımı ⏳)

1. **NodeMCU ESP8266 Fiziksel Derleme ve Flaşlama:**
   - ESP8266 C++ kodu (`firmware/sulama_node/sulama_node.ino`) sentetik ve mantıksal olarak pin çakışması ve aktif-LOW röle güvenliği yönünden güncellenmiştir; ancak gerçek ESP8266 çipine henüz flaşlanmamıştır.
2. **ADS1115 I2C Tezgâh Doğrulaması:**
   - Önerilen pin haritası (SCL=D1, SDA=D2, DHT=D5, Röle=D6, VCC=D7) masaüstü osiloskop/multimetre ve testbed donanımı ile tezgâhta doğrulanacaktır.
3. **Canlı CDS İndirme ve 403 Maliyet/Boyut Sınırı Yönetimi:**
   - Copernicus CDS yeni API'sinde tek istekte 10 değişken x 31 gün x 24 saat talep edildiğinde "403 cost limits exceeded / request too large" hatası oluşmaktadır. Bu durum değişkenleri 5 ayrı gruba bölüp her grup için ayrı geçici dosya indirilmesi ve `xarray.merge` ile birleştirilmesiyle çözülmüştür. 403 hatasında istekler otomatik olarak gün ve değişken bazında parçalanır.
   - **`reanalysis-era5-land-timeseries` Araştırması:** CDS API kataloğunda bağımsız ve doğrulanmış bir `reanalysis-era5-land-timeseries` API uç noktası bulunmamaktadır; ECMWF'nin standart ve resmi veri seti `reanalysis-era5-land`dir. Park koordinatları (Yıldız ve Maçka) için `area` kutusu ile alt kümeleme yapılmaktadır. Değişken adları (`t2m`, `d2m`, `sp`, `tp`, `ssrd`, `strd`, `u10`, `v10`, `swvl1`, `swvl2`), 00:00 UTC kümülatif birikim kuralı ve `valid_time`/`time` zaman koordinatları standarttır.
4. **İSKİ Sayaç Verisi:**
   - Projede hiçbir İSKİ veya kurum verisi depolanmamakta olup, tüm veri boru hatları `tests/fixtures/` sentetik şemalarıyla doğrulanmıştır.

---

## 4. Bilimsel Varsayımlar ve Durumları

- **Toprak Parametreleri:** İstanbul parkları için orta bünyeli tınlı toprak varsayılmıştır ($\theta_{FC} = 0.28\text{ m}^3/\text{m}^3$, $\theta_{WP} = 0.14\text{ m}^3/\text{m}^3$, $Z_r = 0.30\text{ m}$, $p = 0.50$). Durum: `status: assumption`.
- **Sulanan Alan Oranı:** Park poligon alanının %60'ının çim/yeşil sulanan alan olduğu varsayılmıştır (`irrigated_fraction = 0.60`). Durum: `status: assumption`.
- **NDVI Tabanlı Kc:** $K_c = \text{NDVI}^2$ formülü Viyana çalışmasından esinlenmiş deneysel bir modeldir. Türkiye iklimi ve park çimleri için kalibrasyon gerektirir (`status: assumption`).
