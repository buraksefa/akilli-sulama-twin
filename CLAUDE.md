# CLAUDE.md — Akıllı Sulama Dijital İkizi (Yüksek Lisans Tezi)

Dil: Türkçe konuş ve yaz (kod, değişken adları ve commit mesajları İngilizce olabilir).
Bu dosya tezin amacını, bilimsel çerçevesini, kodun gerçek durumunu ve sıradaki işleri anlatır.
Bir şey bu dosyada yoksa uydurma, kullanıcıya sor.

## 1. Kimin için, ne için
- Sahip: Burak Sefa Alpsoy. Galatasaray Üniversitesi Fen Bilimleri Enstitüsü, Akıllı Sistemler
  Mühendisliği yüksek lisans. Danışman: Prof. Dr. Gülfem Alptekin. Teslim hedefi: **Mayıs 2027**.
- Danışmanın temel beklentisi: tez bir "proje" olmaktan öte **bilimsel temelli** olmalı. Her model
  seçimi, parametre ve sonuç; kaynak, ölçüm ya da açıkça etiketli bir varsayımla desteklenmeli.
- Konu: Beşiktaş'taki iki kent parkı için sulama dijital ikizi ve simülasyonu:
  **Yıldız Korusu** ve **Maçka Demokrasi Parkı**. (Fethi Paşa kapsam dışı, geri ekleme.)
- Tez omurgası:
  - **A (ana):** ERA5-Land tabanlı sulama su ihtiyacı ve strateji simülasyonu (S0-S4).
  - **B (ana):** düşük maliyetli sensör kalite kontrolü (QC) ve sanal sensör.
  - **C (isteğe bağlı):** İSKİ tüketim verisiyle doğrulama. Veri gelmezse tez A+B ile tamamlanır.

## 2. Mutlak kurallar
1. **İSKİ verisi** (`data/iski/` ve bağlı LUKS hacmi) yalnızca Burak'a aittir. Açma, okuma,
   listeleme dışında hiçbir şey yapma, içeriğini gösterme, koda gömme, teste koyma.
   Okuduğun her şey Anthropic API'ye gider. Bu veri bulutta/AI araçlarında işlenmeyecek.
2. **Sırlar:** token, parola, API anahtarı, `~/.cdsapirc`, `.env` içeriği; hiçbir dosyaya, loga,
   commit'e, ekrana yazılmaz. Koda varsayılan sır gömme (ör. varsayılan API token'ı).
   Ortam değişkeni yoksa servis hata verip kalkmaz.
3. **Pompa/aktüatör kontrolü yok.** MQTT `sulama/+/cmd` konusuna yayın yapma, `mosquitto_pub`
   kullanma. Sulama komutu üreten kod yalnızca "öneri" üretir, onay Burak'tadır.
4. **Uydurma sayı yok.** Ölçmediğin değeri raporlama; test/komut çıktılarını ham ver.
   Sentetik ve gerçek veri sonuçlarını asla karıştırma; her tabloda ve grafikte kaynağı etiketle
   (`source: era5_land` / `synthetic`).
5. **Parametre disiplini:** her fiziksel parametre `src/twin/config.py` içinde
   `ParameterItem(value, source, status)` ile tanımlanır. `status`: `measured`, `literature`
   (kaynakla), `assumption`. Koda sihirli sayı gömme.
6. Sistem geneli değişiklik (dnf, systemctl, firewall-cmd) için komutu göster, onay bekle.
   SELinux enforcing ve firewalld açık kalır.
7. Her değişiklikten sonra `pytest -q` ve `ruff check` çalıştır; kırık testle bırakma.

## 3. Bilimsel çerçeve (tezin savunması buna dayanır)
- **ETo:** FAO-56 Penman-Monteith, günlük adım. Doğrulama: FAO-56 Örnek 18 = 3,88 mm/gün
  (testte geçiyor). Saatlik varyant deneysel, tezde kullanma.
- **Su dengesi (kök bölgesi):** TAW, RAW, tükenme Dr, Ks, ETa = Ks·Kc·ETo; yağış, sulama
  (verimlilik ile), derin sızma ve yüzey akışı terimleri `model/waterbalance.py` içinde.
  Kc evre bazlı (`model/kc.py`), kış Kc ve NDVI Kc sınırları config'te varsayım olarak etiketli.
- **Veri asimilasyonu:** EnKF (40 üye) ve doğrudan nudging (`model/assimilation.py`).
- **QC:** SIMPaCT kuralları: >%50 eksik, >3 gün boşluk, 120 saatte <%1 değişim (donma),
  24 saatlik kayan medyanla sıçrama, fiziksel aralık (`qc/rules.py`).
- **Karar:** CRITIC ağırlıklı çok kriterli sıralama (`sim/critic.py`).
- **Duyarlılık:** OAT ve Sobol/Morris (SALib). **Arıza enjeksiyonu:** `sim/fault_injection.py`.
- **Stratejiler (`sim/strategies.py`):** S0 sabit takvim (3 günde bir 12 mm), S1 sensör eşiği,
  S2 yalnız ET (sensörsüz), S3 yağış tahminli erteleme (eşik 5 mm), S4 asimile edilmiş ikiz.
  Brüt doz üst sınırı 35 mm.

## 4. ERA5-Land verisi (gerçek, mevcut)
- Hücre: **(41.0 K, 29.0 D)**. İki park da bu tek hücrede. Bu bir kıyı/Boğaz hücresi; arazi ve
  su karışımı nedeniyle sıcaklık/rüzgâr yanlılığı olabilir. Tezde bir sınırlılık olarak belirt.
- Yılları: **2020-2024**, aylar **Nisan-Ekim**, 35 aylık dosya:
  `data/raw/era5/era5land_YYYY_MM.nc` (~8 MB toplam). 2015-2019 ve 2025 henüz **indirilmedi**.
- Birikimli değişkenler (tp, ssrd, strd) her gün 00 UTC'de sıfırlanır. D+1 gününün 00 UTC değeri
  D gününün toplamıdır. Ay sınırında dosyanın ilk satırı bir önceki günün toplamıdır; saatlik artış
  olarak sayma (bu hata bir kez yaşandı ve düzeltildi; temmuz Rs ortalaması 24,72 MJ/m²/gün).
- İşlenmiş çıktı: `data/processed/era5_yildiz_YYYY.csv`. Sütunlar: `rad_mj_m2`, `eto_mm`,
  `rain_mm`, `swvl1`, `swvl2`, `strd_mj_m2` ve diğer günlük meteoroloji alanları.
- Üretim: `twin era5 build`. İndirme: `twin era5 download --park yildiz --years ... --months 4-10`
  (CDS yeni API, `~/.cdsapirc`'yi Burak koyar; 403 maliyet sınırı için değişken grupları
  bölünür, var olan dosyalar atlanır).
- **Henüz yapılmadı:** gerçek veriden yıllık özetin (yağış toplamı, ETo toplamı, yağışlı gün,
  yaz ETo ortalaması) çıkarılıp incelenmesi. Gerçek yıllar arasında belirgin fark beklenir;
  sentetik üretecin yıllar arası ±3 mm gibi dar farkı gerçekçi değildi.

## 5. Kodun gerçek durumu (dürüst envanter)
Proje `akilli-sulama-twin`; paket adı `twin`, CLI: `twin`. Python 3.11, FastAPI, Streamlit,
Typer. Önceki geliştirmeyi "Bob" adlı bir kod asistanı yaptı; inceleme sonuçları:
- Doğrulanmış ve sağlam: günlük PM, su dengesi, config/ParameterItem, ERA5 ay-sınırı düzeltmesi,
  QC kurallarının bağlanması, `server/mosquitto/config/acl` (yalnızca `operator` cmd'ye yazar),
  compose'ta `${VAR:?...}` zorunlu sır ve 127.0.0.1 bağlama.
- **Kritik açık 1 — simülasyon hâlâ sentetik hava ile koşuyor.**
  `sim/engine.py::prepare_season_weather` içinde `generate_synthetic_era5(...)` çağrılıyor,
  gerçek `data/processed/era5_yildiz_YYYY.csv` kullanılmıyor. Yani şu an `twin compare` ve
  `/simulate`, `/compare` sonuçları **sentetik** hava üzerinde. Tezin A kolu için en öncelikli iş
  bu (bkz. Bölüm 6, ilk madde).
- **Kritik açık 2 — API varsayılan token'ı:** `api/app.py` bazı sürümlerde
  `os.environ.get("API_AUTH_TOKEN", "gsutwin2026")` içeriyor. Güncel sürümde
  `get_api_secret_token()` olmalı ve token yoksa hata fırlatmalı. Doğrula; varsayılan sır varsa kaldır.
- **Doğrulanacak 3 — S4/EnKF mantığı:** `S4AssimilatedTwin.decide` içinde
  `enkf.analysis_step(sensor_theta_obs)` yalnızca gözlemle çağrılıyor; ETo/yağış/sulama ile
  tahmin (forecast) adımının nerede çalıştığı belirsiz. Eğer ikiz modeli ilerletmeden yalnızca
  analiz yapıyorsa S4 gerçek asimilasyon değildir. Kodu oku, gerekiyorsa tahmin adımını
  (su dengesi ile) ekle, birim testi yaz.
- **Doğrulanacak 4 — adil karşılaştırma:** yağış "tahmini" gerçek ertesi gün yağışı + gürültü
  (kâhin tahmin). Bunu tezde varsayım olarak belirt ve tahmin hatası duyarlılığını ekle. Simülasyon
  tek rastgele tohumla (42) koşuyor; çoklu tohum + güven aralığı ekle.
- `/telemetry`, `/testbed/state`, `/testbed/advice` uç noktaları **sentetik/sabit** yanıt veriyor
  (`source: synthetic` etiketli). Gerçek InfluxDB bağlantısı yok.
- Sunucu yığını `server/docker-compose.yml`: Mosquitto, Telegraf, InfluxDB 2, Grafana, API, UI.
  RHEL'de Podman ile çalışacak (bkz. RHEL kurulum görevi).

## 6. Sıradaki işler (öncelik sırasıyla)
1. **Gerçek ERA5'i simülasyona bağla:** `prepare_season_weather` önce
   `data/processed/era5_yildiz_{yıl}.csv` okusun, yoksa açıkça `source="synthetic"` etiketiyle
   sentetiğe düşsün. DataFrame'e `source` sütunu/attrs ekle; CLI/API çıktısında göster.
   Test: ETo sütunu CSV ile birebir tutarlı; yıl yoksa uyarı.
2. `twin era5 build` ile gerçek yıllık özeti çıkar (`docs/server/ERA5_SUMMARY.md`), Burak'a raporla.
3. `twin compare` ile S0-S4'ü 2020-2024 gerçek ERA5 üzerinde koştur; CRITIC sıralamasını
   (kriter ağırlıklarıyla) kaydet. Çoklu tohum ile belirsizlik bandı üret.
4. EnKF/S4 mantığını doğrula ve düzelt (Bölüm 5, madde 3). Asimilasyon kazancını sensör gürültüsü
   ve arıza senaryolarına göre ölç.
5. B kolu: sensör QC performansı. Arıza enjeksiyonu (sürüklenme, donma, sıçrama, boşluk) ile
   kural tabanlı QC'nin yakalama oranı (duyarlılık/özgüllük); sanal sensör için baz modeller
   (ör. ERA5 + su dengesi tabanlı tahmin, sonra Isolation Forest/ARIMA/küçük MLP) ve kıyaslama.
6. Duyarlılık: OAT ve Sobol (S1, ST) parametre sıralaması; hangi parametrelerin sonuçları
   belirlediğini göster (tezde "hangi ölçüm önemli" argümanı).
7. Doğrulama zemini: 2015-2019 ve 2025 ERA5 indirmesi (tmux, kesintiye dayanıklı).
8. İSKİ verisi gelirse (C kolu): **Burak yapar**, sen yalnızca analiz kodunu hazırlarsın;
   veri üzerinde çalışma izni yoktur.
9. Tez metnine girdi: her sonuç için yöntem paragrafı taslağı ve şekil/tablo kaynak notu üret.

## 7. Dış süreçler (bilgi, kodlama gerekmez)
- İSKİ: Bilgi İşlem Dairesi Başkanı ile görüşme yapıldı (22 Ekim 2026). Resmî süreç için
  Su Kayıpları ve Basınç Yönetimi Dairesi'ne üniversite KEP'iyle dilekçe + Proje Bilgi Formu +
  Gizlilik Taahhütnamesi gerekiyor; dilekçe henüz hazır değil.
- İBB Park ve Bahçeler Müdürlüğü: parkların sulama sistemi yapısı (zone, debi, uygulama hızı)
  için e-posta gönderildi; yanıt yok. Parametreler o zamana dek `assumption` etiketli kalır.
- Bu süreçlerin sonuçlarını sen takip etme; Burak ne zaman veri gelirse söyler.

## 8. Çalışma biçimi
- Küçük, test edilebilir adımlar; her adımda ne değiştiğini, hangi testin geçtiğini ve neyin
  doğrulanmadığını söyle.
- Bir bulgu tezin iddiasını değiştirecekse (ör. S4 beklenen avantajı göstermiyorsa) bunu gizleme,
  dürüstçe raporla. Negatif sonuç da bilimsel katkıdır.
- Uzun koşuları (Sobol, çoklu tohum) tmux içinde çalıştır, çıktıyı `outputs/` altına yaz
  ve süreleri ham ver.
