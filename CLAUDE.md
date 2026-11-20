# CLAUDE.md — Akıllı Sulama Dijital İkizi (Yüksek Lisans Tezi)

Dil: Türkçe konuş ve yaz (kod, değişken adları ve commit mesajları İngilizce olabilir).
Bu dosya tezin amacını, bilimsel çerçevesini, kodun durumunu ve sıradaki işleri anlatır.
Bu dosyada olmayan bir şeyi uydurma; kullanıcıya sor. Matematiksel çalışma için `docs/MATH_STUDY.md` esastır.

## 1. Kimin için, ne için
- Sahip: Burak Sefa Alpsoy. Galatasaray Üniversitesi Fen Bilimleri Enstitüsü, Akıllı Sistemler Mühendisliği
  yüksek lisans. Danışman: Prof. Dr. Gülfem Alptekin. Teslim hedefi: **Mayıs 2027**.
- Danışmanın beklentisi: tez bir "proje" olmaktan öte **bilimsel temelli** olmalı. Her model seçimi, parametre ve sonuç
  kaynakla, ölçümle ya da açıkça etiketli bir varsayımla desteklenmeli.
- Konu: Beşiktaş'taki iki kent parkı için sulama dijital ikizi ve simülasyonu: **Yıldız Korusu** ve
  **Maçka Demokrasi Parkı**. Fethi Paşa kapsam dışı, geri ekleme.
- Omurga: **A** ERA5-Land tabanlı su ihtiyacı ve strateji simülasyonu (S0–S4); **B** düşük maliyetli sensör kalite
  kontrolü ve sanal sensör; **C** (isteğe bağlı) İSKİ tüketim verisiyle doğrulama. C gelmezse tez A+B ile tamamlanır.
- Araştırma soruları: RQ1 sensör hatalarının karara etkisi; RQ2 stratejilerin su/stres karşılaştırması (CRITIC);
  RQ3 parametre duyarlılığı. Ayrıntı: `docs/THESIS_FRAME.md`.

## 2. Mutlak kurallar
1. **İSKİ verisi** (`data/iski/` ve bağlı LUKS hacmi) yalnızca Burak'a aittir. Açma, okuma, içeriğini gösterme, koda
   gömme, teste koyma. Okuduğun her şey Anthropic API'ye gider. Bu veri bulutta ya da yapay zekâ araçlarında işlenmez;
   dilekçede bu söz verildi. Analiz kodunu sentetik şemaya uygun yaz, Burak kendisi çalıştırır.
2. **Sırlar:** token, parola, API anahtarı, `~/.cdsapirc`, `.env` içeriği hiçbir dosyaya, loga, commit'e, ekrana yazılmaz.
   Koda varsayılan sır gömme. Ortam değişkeni yoksa servis hata verip kalkmaz.
3. **Pompa/aktüatör kontrolü yok.** MQTT `sulama/+/cmd` konusuna yayın yapma, `mosquitto_pub` kullanma. Sulama
   komutu üreten kod yalnızca öneri üretir; onay Burak'ındır.
4. **Uydurma sayı yok.** Ölçmediğin değeri raporlama; komut çıktılarını ham ver. Sentetik ve gerçek sonuçları karıştırma;
   her tablo ve grafikte kaynağı etiketle (`era5_land` / `synthetic` / `synthetic_from_era5`).
5. **Parametre disiplini:** her fiziksel parametre `src/twin/config.py` içinde `ParameterItem(value, source, status)`
   ile tanımlanır. `status`: `measured`, `literature` (kaynakla), `assumption`. Koda sihirli sayı gömme.
6. Sistem geneli değişiklik (dnf, systemctl, firewall-cmd) için komutu göster, onay bekle. SELinux enforcing ve
   firewalld açık kalır.
7. Her değişiklikten sonra `pytest -q` ve `ruff check`; kırık testle bırakma.

## 3. Bilimsel çerçeve
- **ETo:** FAO-56 Penman-Monteith, günlük adım. Doğrulama: FAO-56 Örnek 18 = 3,88 mm/gün (testte geçiyor).
  Saatlik varyant deneysel, tezde kullanma.
- **Su dengesi:** TAW, RAW, tükenme Dr, Ks, ETa = Ks·Kc·ETo (`model/waterbalance.py`); Kc evre bazlı (`model/kc.py`).
- **Asimilasyon:** EnKF (40 üye) ve nudging (`model/assimilation.py`).
- **QC:** SIMPaCT kuralları: >%50 eksik, >3 gün boşluk, 120 saatte <%1 değişim (donma), 24 saatlik kayan medyanla
  sıçrama, fiziksel aralık (`qc/rules.py`).
- **Karar:** CRITIC çok kriterli sıralama (`sim/critic.py`). **Duyarlılık:** OAT ve Sobol/Morris. **Arıza enjeksiyonu:**
  `sim/fault_injection.py`.
- **Stratejiler (`sim/strategies.py`):** S0 sabit takvim (3 günde bir 12 mm), S1 sensör eşiği, S2 yalnız ET,
  S3 tahminli erteleme (eşik 5 mm), S4 asimile ikiz; brüt doz üst sınırı 35 mm.
- **Matematiksel model:** verimlilik ölçütleri, bilgi düzeyleri, kâhin alt sınırı, sensör yanlılığı ve Kalman analitik
  sonuçları `docs/MATH_STUDY.md` içinde; `math_checks.py` bunları doğrular.

## 4. ERA5-Land verisi (gerçek, mevcut)
- Hücre: **(41,0 K; 29,0 D)**, iki park da bu tek hücrede (kıyı/Boğaz hücresi; sıcaklık ve rüzgâr yanlılığı olabilir,
  tezde sınırlılık olarak yaz).
- 2020–2024, Nisan–Ekim: `data/raw/era5/era5land_YYYY_MM.nc` (35 dosya, ~8 MB). 2015–2019 ve 2025 **indirilmedi**.
- Birikimli değişkenler (tp, ssrd, strd) her gün 00 UTC'de sıfırlanır; D+1'in 00 UTC değeri D'nin toplamıdır. Ay
  sınırında dosyanın ilk satırı önceki günün toplamıdır, saatlik artış sayma (bu hata bir kez yaşandı, düzeltildi;
  temmuz Rs ortalaması 24,72 MJ/m²/gün).
- İşlenmiş çıktı: `data/processed/era5_yildiz_YYYY.csv` (`rad_mj_m2`, `eto_mm`, `rain_mm`, `swvl1`, `swvl2`,
  `strd_mj_m2` vb.). Üretim: `twin era5 build`. İndirme: `twin era5 download --park yildiz --years ... --months 4-10`
  (CDS yeni API; `~/.cdsapirc`'yi Burak koyar).
- **Henüz yapılmadı:** gerçek veriden yıllık özet (yağış toplamı, ETo toplamı, yağışlı gün, yaz ETo ortalaması).
  Gerçek yıllar arasında belirgin fark beklenir.

## 5. Elimizdeki halka açık veri (`data/public/`)
- Park poligonları: Yıldız Korusu 389.760 m², Maçka 139.419 m² (İBB Açık Veri, 2025-04-08). Poligon alanı sulanan
  alan değildir; `irrigated_fraction` açık varsayım olarak config'te durmalı.
- İBB yıllık yeşil alan suyu (2017–2025): 13,4–18,8 milyon m³/yıl. **Kapsamı belirsiz** (tüm İstanbul mu, hangi alan);
  yalnızca büyüklük sırası için kullan. Kapsam İBB'den resmî olarak sorulacak.
- Beşiktaş yeşil alan poligonları (32 adet, toplam 1.158.349 m²; Park 12, Karayolu/refüj 3, Cadde 9, Koru 1,
  Meydan 1, Kamu 5, Metro çıkışı 1): ölçekleme ve bağlam için.

## 6. Kodun durumu (2026-11-20'de güncel kodda doğrulandı)
Önceki geliştirmeyi "Bob" adlı bir kod asistanı yaptı. Doğrulanmış sağlam kısımlar: günlük PM, su dengesi, config/
ParameterItem, ERA5 ay-sınırı düzeltmesi, QC kurallarının bağlanması, Mosquitto ACL'i (yalnızca `operator` cmd'ye yazar),
compose'ta zorunlu sır ve 127.0.0.1 bağlama.

**Kapanan açıklar**
- Gerçek ERA5 simülasyona bağlı: `prepare_season_weather(source="auto")` önce `data/processed/era5_{park}_{yıl}.csv`
  okur, yoksa UserWarning ile `source="synthetic"` etiketli sentetiğe düşer; CLI/API çözülen kaynağı gösterir.
- `api/app.py` varsayılan token içermiyor; `get_api_secret_token()` token yoksa hata verir.
- Varsayılan çim parametreleri FAO-56 serin iklim çimine düzeltildi (Kc 0,90/0,95/0,95; Zr 0,5 m; p 0,40;
  Tablo 12/22 sayfadan okundu, `verified`). TAW 70 mm, RAW 28 mm. Eski config sonuçları `outputs/*_v1_eski_config.csv`.

**Hâlâ açık**
1. S2 ve S3 gerçek durumu (`state_depletion_mm`) görüyor; truth ile model sürücüleri ayrı değil. Ayrık sürüm yalnız S5
   için var: `EstimatedPersistenceJIT` (kestirici true/sensor/openloop/enkf, ETo yanlılığı `b`),
   `docs/model/VERIMLILIK_MODELI.md` §12.
2. S4'te EnKF tahmin adımı var ama **zamanlaması tutarsız**: `forecast_step` bugünün ETo/yağışıyla (ileriye bakma) koşuyor,
   sonra Dr_{t-1}'i ölçen gözlemle `analysis_step` yapılıyor (§12.4). Düzeltme Burak'ın onayını bekliyor.
3. Yağış tahmini kâhin (ertesi gün gerçek yağış + N(0, 1 mm)); tahmin hatası duyarlılığı yok. S1–S4 varsayılan tek
   tohumla (42) koşuyor (`simulate_strategy_season(seed=...)` var); S5 deneyleri 10 tohumla.
4. `engine.simulate_strategy_season` arıza enjeksiyonu her günü tek elemanlı seriyle çağırıyor; **kayma ve donma fiilen
   oluşmuyor**, yalnız yanlılık ve kopma çalışıyor. RQ1 deneyleri için düzeltilmeli. Sanal park (`sim/virtual_park.py`)
   durumlu sensörlerle bu sorundan bağımsız.
5. 35 mm brüt doz üst sınırı (`max_gross_dose_mm`, varsayım) yeni RAW ile S1–S4'ün her sulamasını kesiyor; bu stratejilerin
   karşılaştırması bu varsayıma bağlı (§10.3). `strategies.py` içinde 35.0 hâlâ sabit yazılı.
6. Ağaç, çalı, mevsimlik çiçek için doğrulanmış bitki profili yok (WUCOLS/Peyzaj Katsayısı kaynağına erişilemedi);
   bu zonlar simüle edilmez, `no_verified_profile` olarak işaretlenir.
7. `/telemetry`, `/testbed/*` uç noktaları sentetik (`source: synthetic`); InfluxDB bağlantısı yok.

**Yapılan çalışmalar (sonuçlar `docs/model/VERIMLILIK_MODELI.md`, gerçek ERA5 2020–2024, Yıldız)**
- Kâhin tam zamanında sulama = stressiz en az su; JIT optimalliği ispatlandı (Önerme 1), LP ile her yıl sayısal sertifika
  (`sim/efficiency.py`, `twin efficiency`). Bu, MATH_STUDY E1'in λ → ∞ (stressiz) ucudur; λ taraması yapılmadı.
- S5 kalıcılık JIT (öğrenmesiz) %10 güvenlik payıyla stressiz ve kâhine ~9 mm/sezon yakın; S6 DAgger öğrenilmiş politika
  S5'e anlamlı katkı vermedi (negatif sonuç) (`sim/learned_policy.py`, `twin learned-policy`, `twin noisy-state`).
- Sanal park test ekranı: `src/twin/ui/sanal_park.py`, senaryo `data/scenarios/yildiz_sanal.json` (şematik varsayım).
  Kod özel GitHub deposunda (`buraksefa/akilli-sulama-twin`), ekran Streamlit Community Cloud'da.

## 7. Sıradaki işler
1. Yöntem belgelerini birleştir: `docs/MATH_STUDY.md` (formülasyon, E1–E6) ile `docs/model/VERIMLILIK_MODELI.md`
   (gerçek ERA5 sonuçları) tek yöntem metninde; MATH_STUDY'deki kontrol parametreleri (θFC 0,32, θWP 0,15, Zr 0,30,
   p 0,50) config'ten farklıdır, analitik sayılar yalnız o değerler için geçerli.
2. §6 açık 1, 2 ve 4'ü düzelt (S2/S3 için truth/model ayrımı, S4 zamanlaması, arıza enjeksiyonu); her biri için test.
3. `twin era5 build` ile gerçek yıllık özeti çıkar (yağış, ETo toplamı, yağışlı gün, yaz ETo ortalaması), Burak'a göster.
4. MATH_STUDY E1 (λ taraması, DP kâhin), E2, E3'ü gerçek ERA5 ile koş; `outputs/` altına kaynak etiketli yaz, ham tablo göster.
5. E4–E6 (yanlılık durumlu asimilasyon, Sobol, güç analizi); sonra tez yöntem ve bulgular bölümü taslağı.
6. Daha sonra: 2015–2019 ve 2025 ERA5 indirmesi (tmux, kesintiye dayanıklı); sensör QC'yi sanal parka bağla (B kolu); testbed.

## 8. Dış süreçler (bilgi, kodlama gerekmez)
- İSKİ: Bilgi İşlem Dairesi Başkanıyla görüşme 22 Ekim 2026'da yapıldı. Resmî süreç: Su Kayıpları ve Basınç Yönetimi
  Dairesi'ne üniversite KEP'iyle dilekçe + Proje Bilgi Formu + Gizlilik Taahhütnamesi. Dilekçe hazır, Burak
  haftaya resmî yoldan gönderecek.
- İBB Park ve Bahçeler: e-postaya dönüş yok; resmî dilekçe hazır (sulama sistemi verisi, İSKİ'ye muvafakat, yıllık su
  verisinin kapsamı). Gelen veri parametrelerdeki `assumption` etiketlerini değiştirir.
- Bu süreçleri takip etme; veri geldiğinde Burak söyler.

## 9. Çalışma biçimi
- Küçük, test edilebilir adımlar; her adımda ne değiştiğini, hangi testin geçtiğini ve neyin doğrulanmadığını söyle.
- Bir bulgu beklenen sonucu desteklemiyorsa (ör. S4 avantaj göstermiyorsa) gizleme. Negatif sonuç da bilimsel katkıdır.
- Uzun koşuları tmux içinde çalıştır, çıktıyı `outputs/` altına yaz, süreleri ham ver.
