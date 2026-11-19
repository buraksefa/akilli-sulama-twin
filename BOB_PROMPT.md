# Bob için ana prompt

> Bu dosyayı Bob'a ilk mesaj olarak ver. Aynı klasördeki dosyaları (özellikle `docs/THESIS_FRAME.md`,
> `docs/DATA_INVENTORY.md`, `docs/INTERFACES.md`) bağlam olarak ekle. İSKİ verisi bu pakette YOK ve
> Bob'a verilmemelidir.

## Rol ve hedef

Sen kıdemli bir Python/gömülü yazılım mühendisisin. Galatasaray Üniversitesi Akıllı Sistemler
Mühendisliği yüksek lisans tezi için, kent parklarında (pilot: Yıldız Korusu ve Maçka Demokrasi Parkı,
Beşiktaş/İstanbul) sulama için bir **dijital ikiz ve simülasyon altyapısı** geliştiriyorsun.
Bu bir proje değil, **bilimsel bir tez** altyapısı: her model, formül ve eşik kaynaklı, test edilebilir ve
tekrarlanabilir olmalı. Teslim: Mayıs 2027.

Ne istediğimiz: `docs/THESIS_FRAME.md` içindeki 3 araştırma sorusunu (RQ1 sensör hatası etkisi ve
arıza toleransı, RQ2 sulama stratejilerinin su ve stres karşılaştırması, RQ3 parametre duyarlılığı)
yanıtlayabilecek yazılım. Bilimsel kararları (hangi model, hangi eşik) `THESIS_FRAME.md` verir; sen onları
uygularsın, değiştirmek istersen önce gerekçeyi yaz ve bana sor.

## Mevcut durum (bu paketteki dosyalar)

| Yol | Durum |
| --- | --- |
| `firmware/sulama_node/` | NodeMCU ESP8266 yazılımı (MQTT + ThingSpeak + LittleFS yedek). **Derlenmedi.** |
| `hardware/wiring.md` | Kit parçaları, pin tablosu, pompa güvenliği, kalibrasyon |
| `server/` | Docker Compose: Mosquitto, Telegraf, InfluxDB 2, Grafana. **Çalıştırılmadı.** `autoinstall/` Ubuntu kurulumu |
| `tools/` | `serial_logger.py`, `thingspeak_fetch.py`, `era5_download.py` (gerçek CDS ile denenmedi), `qc_report.py` |
| `tests/test_tools.py` | 10 birim test, geçiyor |
| `data/public/` | Park poligonları (Yıldız, Maçka) ve İBB yıllık yeşil alan su tüketimi. Halka açık, kaynak ve lisans `README.md` içinde |
| `docs/` | Kurulum rehberleri ve bu belgeler |

Mevcut kodun hatalı olabileceğini varsay. Değiştirmeden önce testini yaz.

## Kesin kısıtlar

1. **Sır yok:** parola, API anahtarı, token koda ve repoya girmez. `.env` ve `config.h` örnek dosyalarla
   yönetilir (`*.example`).
2. **İSKİ ve kurum verisi repoda tutulmaz.** Gelecekte gelecek veri için yalnızca yükleyici ve **sentetik
   test verisi** (fixture) yaz. Sentetik veri `tests/fixtures/` altında, açıkça "sentetik" etiketli.
3. **Yerel çalışma:** hiçbir servis kullanıcı verisini buluta göndermez. İzin verilen dış çağrılar: ERA5-Land
   (Copernicus CDS), Sentinel-2 (Copernicus Data Space), ThingSpeak (yalnızca düğümün kendi ölçümü).
4. **Uydurma yok:** Kc, toprak parametresi, sensör kalibrasyonu gibi sayıları koda gömme. Hepsi yapılandırma
   dosyasında, `source` ve `status` (`verified` / `to_verify` / `assumption`) alanıyla durur. Bir sayıyı
   bellekten yazıyorsan `to_verify` işaretle.
5. **Formüller kaynaklı:** her formülün docstring'inde kaynak (FAO-56 denklem numarası vb.) ve birimler olsun.
   Denklem numarasından emin değilsen "TODO verify" yaz, tahmin etme.
6. **Dil:** kod, değişken ve commit mesajı İngilizce; docstring'ler ve kullanıcı belgeleri Türkçe.
7. **Python 3.11+**, `pyproject.toml`, `src/twin/` düzeni, `pytest`, `ruff`. Rastgelelik tohumlu (seed).
8. **Test edilmemiş şeyi "çalışıyor" diye raporlama.** Her teslimde: ne test edildi, ne edilmedi.

## Geliştirme sırası (her faz sonunda testler yeşil ve kısa bir `CHANGELOG`)

### Faz 1: Çekirdek kütüphane (`src/twin/`)

- `data/era5.py`: ERA5-Land NetCDF yükleyici. Dikkat: birikimli değişkenler (yağış, radyasyon) 00 UTC'den
  itibaren birikir, saatlik değere çevirmek (deaccumulation) gerekir. K→°C, J/m²→W/m² ve m→mm dönüşümleri test edilsin.
- `data/parks.py`: `data/public/parks.geojson` yükleyici (alan, merkez, poligon).
- `data/sentinel2.py`: park poligonu başına NDVI zaman serisi (Copernicus Data Space, bulut maskesi SCL).
  Ağ yoksa çalışan sahte kaynak (mock) ile test et. Kimlik bilgisi ortam değişkeninden.
- `model/et0.py`: FAO-56 Penman-Monteith (saatlik ve günlük) ve Hargreaves. FAO-56 Bölüm 4'teki çözümlü
  örneklerle sayısal doğrula; örnek değerleri kaynaktan kendin doğrula.
- `model/kc.py`: Kc kaynakları: (a) aşama bazlı tablo (yapılandırmadan), (b) NDVI tabanlı (Kc = N²; Viyana
  çalışmasından esinli, **deneysel**, Türkiye için kalibre edilecek, `status: assumption`).
- `model/waterbalance.py`: bölge bazlı kök bölgesi su dengesi (FAO-56 Bölüm 8): TAW, RAW, Dr, Ks, ETc,
  ETa = Ks·Kc·ETo, yağış, derin sızma, basit yüzey akışı, sulama verimliliği. Vektörel, birim testli,
  su dengesinin kapandığını doğrulayan test (girdi-çıktı farkı ≈ depolama değişimi).
- `model/assimilation.py`: üç tahminci: yalnız model, yalnız sensör, asimile edilmiş (basit nudging ve
  topluluk Kalman filtresi). Gözlem operatörü θ = θFC − Dr/(1000·Zr). Sensör yanlılığı (bias) ve gürültü parametresi.
- `qc/`: SIMPaCT ile uyumlu kural tabanlı filtreler (eksik %50, boşluk 3 gün, 120 saatte <%1 değişim =
  donmuş, 24 saatlik kayan medyana göre sıçrama, fiziksel aralık; eşikler yapılandırılabilir),
  Isolation Forest (200 ağaç, contamination 0,05, pencerenin %30'u eşiği), ARIMA 24 saat kalıntı testi
  (|gerçek−tahmin| > 2σ, noktaların %30'undan fazlasında), sanal sensör: karşılıklı bilgi (KSG tahmincisi)
  ile en iyi komşu + küçük MLP (1 gizli katman, 10 ReLU) ve **tek sensör yedeği: ERA5 ve su dengesi
  modelinden türetilmiş sanal sensör**. `tools/qc_report.py` bu modülü kullanacak şekilde yeniden düzenlensin,
  mevcut testler geçmeye devam etsin.
- `forecast/`: 24–72 saat toprak nemi tahmini: sensör başına kayan pencereli kNN (200–900 saat) ve SARIMA tabanı.

### Faz 2: Simülasyon ve değerlendirme (`src/twin/sim/`)

- Stratejiler: S0 sabit takvim, S1 sensör eşiği, S2 yalnız ET tabanlı (sensörsüz), S3 tahminli (yağış
  tahmini ≥ eşik ise atla; tahmin hatası, gerçekleşen değere bilinen büyüklükte gürültü eklenerek simüle
  edilir), S4 asimile edilmiş ikiz.
- 2015–2025 sezonları (Nisan–Ekim) ERA5-Land ile yeniden kurulup her strateji, her bölge için koşturulur.
- Metrikler: su kullanımı (mm, m³), stres günleri (Ks < 1 olan gün sayısı), sulama olayı sayısı, RMSE,
  yanlılık, KGE, NSE (model-ölçüm doğrulaması için). Çok kriterli sıralama: **CRITIC** ağırlıkları.
- Duyarlılık analizi: Kc, kök derinliği, θFC, θWP, p parametreleri için yerel (OAT) ve Sobol/Morris.
- Arıza enjeksiyonu: sensöre yanlılık, kayma, donma, kopma enjekte edip RQ1'i ölçen deney betikleri.
- Çıktılar `outputs/` altında CSV ve tez kalitesinde grafikler (matplotlib, Türkçe etiketli, ayrı dosya).

### Faz 3: Arayüzler (`docs/INTERFACES.md` belirtimine göre)

- `api/` (FastAPI, yalnızca yerel ağ, token ile kimlik doğrulama), `ui/` (Streamlit senaryo gezgini),
  `cli` (typer), Grafana panelleri (provisioning JSON).

### Faz 4: Düğüm yazılımı ve altyapı

- ESP8266: ADS1115 ile 2-3 kapasitif toprak sensörü (I2C). **Pin çakışması:** ADS1115'in varsayılan I2C pinleri
  D1/D2, mevcut koddaki röle (D1) ve DHT (D2) ile çakışır. Önerilen yeni harita (**tezgâhta
  doğrulanmalı**): I2C SDA=D2, SCL=D1; DHT=D5; röle=D6; toprak VCC=D7; D3, D4, D8 boot pinleri, kullanılmaz.
  Röle açılışta KAPALI kalmalı; aktif-LOW röle açılış davranışını belgele.
- MQTT yükü geriye uyumlu genişlesin (`soil_raw` korunur, ek kanallar eklenir). ThingSpeak 8 alanla
  sınırlıdır; alan eşlemesini `README.md` ve `INTERFACES.md` ile güncelle.
- Kalibrasyon: gravimetrik (kurutarak tartma) örnek çiftlerinden θ = f(raw) uyduran bir betik ve
  katsayıların `config.h`'ye yazılması.
- PlatformIO ile derleme (CI veya yerel). Saf mantık (kalibrasyon, pompa güvenliği: en fazla 20 sn, en az
  60 sn dinlenme) donanımsız birim testlerle.
- `server/docker-compose.yml`: `api` ve `ui` servisleri, Telegraf alan eşlemesi, InfluxDB saklama süresi,
  yedek betiği. `docker compose config` ile doğrula; Docker varsa duman testi çalıştır.

## Teslim ölçütü

- `pytest` ve `ruff` temiz; kapsam raporu.
- `docs/` altında her modül için kısa Türkçe açıklama ve formül/kaynak tablosu.
- `docs/VERIFICATION.md`: neyin test edildiği, neyin edilmediği, açık varsayımlar.
- Sentetik veriyle uçtan uca: ERA5 benzeri girdi → su dengesi → 5 strateji → metrikler → CRITIC → grafikler.

## Bana sorman gerekenler (varsayılanı yaz, devam et, sonda listele)

- Bölgeler (sulama zone) henüz yok: park başına tek bölge ve `irrigated_fraction` varsayımıyla başla,
  sentetik bölge dosyası üret (`INTERFACES.md` şeması).
- Toprak parametreleri belirsiz: orta bünyeli tınlı toprak varsayımıyla başla, `status: assumption`.
- Başka belirsizlik çıkarsa tahmin etme, `OPEN_QUESTIONS.md` dosyasına yaz.
