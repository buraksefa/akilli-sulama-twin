# Tezin bilimsel çerçevesi

Çalışma başlığı (taslak): *Kent parklarında sulama için dijital ikiz tabanlı karar desteği: düşük maliyetli
sensör belirsizliği altında toprak su dengesi modeli ve strateji karşılaştırması (Yıldız ve Maçka parkları pilotu).*

Danışman: Prof. Dr. Gülfem Alptekin. Teslim hedefi: Mayıs 2027.

## 1. Kavramsal çerçeve

Dijital model, dijital gölge ve dijital ikiz ayrımı (Kritzinger vd., 2018: veri akışının yönüne göre,
*bellekten, doğrulanmadı*). Bir ikizde fiziksel nesne, sanal model ve **iki yönlü** veri akışı bulunur
(Nasirahmadi ve Hensel, 2022). Bu tezde:

- **Park ölçeği (Yıldız, Maçka):** sensör yok. Halka açık veriler (ERA5-Land, Sentinel-2, park poligonları) ve
  varsa kurum verisiyle sanal model ve simülasyon. Adı: **dijital model/gölge**.
- **Testbed (saksı veya balkon):** NodeMCU ölçer, model durumu günceller, röle pompayı sürer. Adı:
  **dijital ikiz** (iki yönlü döngü).

Bu ayrım, tek düğümle "ikiz" iddiasını dürüst ve savunulabilir kılar.

## 2. Araştırma soruları

- **RQ1.** Düşük maliyetli toprak nemi sensörünün hataları (yanlılık, kayma, donma, kopma) sulama kararının
  kalitesini ne kadar bozar? Arıza tespiti, sanal sensör ve veri asimilasyonu bunu ne kadar azaltır?
- **RQ2.** Sulama stratejileri (sabit takvim, sensör eşiği, yalnız ET, tahminli, asimile edilmiş ikiz)
  su kullanımı ve bitki stresi açısından nasıl karşılaştırılır? (CRITIC ile çok kriterli sıralama)
- **RQ3.** Sonuçlar model parametrelerine (Kc, kök derinliği, toprak su tutma, tükenme oranı p) ne kadar
  duyarlıdır? Hangi parametre için yerinde ölçüm en değerlidir?

Hipotezler (sınanacak, kanıtlanmış değil): H1 asimilasyon, yalnız model ve yalnız sensörden daha küçük
RMSE verir; H2 arıza varken sanal sensör kararın kalitesini korur; H3 ET tabanlı ve asimile edilmiş
stratejiler sabit takvime göre aynı stres düzeyinde daha az su kullanır.

## 3. Yöntem

### 3.1 Fiziksel çekirdek: toprak su dengesi (FAO-56)

Kök bölgesi tükenmesi, günlük (veya saatlik) adım:

```
TAW = 1000 · (θFC − θWP) · Zr                 [mm]
RAW = p · TAW                                 [mm]
Ks  = (TAW − Dr) / ((1 − p) · TAW)   Dr > RAW ise, aksi halde 1
ETc = Kc · ETo
ETa = Ks · Kc · ETo
Dr,i = Dr,i-1 − (P − RO) − I − CR + ETa + DP
```

(FAO-56 Bölüm 8; denklem numaraları kaynaktan doğrulanacak.) `ETc` ile `ETa` ayrımı önemlidir:
Viyana çalışmasının SPEI tabanlı katsayıları (0,5 ve 0,8) deneysel bir yamadır; bizim modelde stres
doğrudan Ks ile, gerçek toprak nemi üzerinden gelir.

ETo: FAO-56 Penman-Monteith (birincil) ve Hargreaves (karşılaştırma). İkisinin farkı duyarlılık
analizinin bir parçasıdır. ERA5-Land, PM için gereken değişkenleri verir (sıcaklık, çiy noktası,
radyasyon, rüzgâr, basınç); ERA5-Land çözünürlüğü (0,1°) parkları ayırmaz, yerel düzeltme için MGM veya
İBB istasyonu gelirse kullanılacak.

Kc: başlangıç aşama bazlı (FAO-56 tablosu ve WUCOLS, yapılandırmada `to_verify`), alternatif NDVI tabanlı.
Viyana çalışmasındaki Kc = N² ve çim Kc 0,75 / çayır 0,59 değerleri **Viyana'ya özgüdür**, İstanbul için
doğrudan kullanılmaz, kalibrasyon başlangıcı olarak bile `assumption` etiketlenir.

NDVI uyarısı: Yıldız Korusu büyük ölçüde ağaçlıklı. 10 m NDVI ağaç tacından etkilenir, çim Kc'si vermez.
Sulanan çim alanlarını ayıran bir maske (kurum verisi veya yüksek çözünürlüklü görüntü) gerekir.

### 3.2 Veri asimilasyonu

Gözlem operatörü θ = θFC − Dr / (1000 · Zr). Üç tahminci karşılaştırılır: model, sensör, asimile
(nudging ve topluluk Kalman filtresi). Sensör hatası modeli: θ_obs = a·θ_true + b + ε.

### 3.3 Veri kalitesi ve arıza toleransı (SIMPaCT ile uyumlu)

Kural tabanlı: eğitim penceresinde %50'den fazla eksik; 3 günü aşan boşluk; 120 saat boyunca mutlak
değişim %1'in altı (donmuş); fiziksel aralık dışı; 24 saatlik kayan medyana göre sıçrama.
Model tabanlı: mevsimsel/haftalık fark alınmış seride Isolation Forest (200 ağaç, contamination 0,05;
pencerenin %30'undan fazlası anormalse arıza); 24 saatlik ARIMA tahminine göre |gerçek−tahmin| > 2σ ve
noktaların %30'undan fazlasında arıza.
Sanal sensör: Kraskov-Stögbauer-Grassberger karşılıklı bilgisiyle en iyi komşu + küçük MLP
(1 gizli katman, 10 ReLU). Tek sensörlü durumda: ERA5 ve su dengesinden türetilmiş sanal sensör.

Kaynak: Koçyiğit vd., 2025 (SIMPaCT). Bu eşikler makalenin tam metninden doğrulandı.

### 3.4 Simülasyon deneyleri

- **Sezonlar:** 2015–2025 Nisan–Ekim, ERA5-Land ile yeniden kurulur. Kış verisi sulama dinamiği taşımadığı
  için testbed yaz davranışını kanıtlamaz; yaz davranışı tarihsel sezonlarda simüle edilir.
- **Stratejiler:** S0 sabit takvim, S1 sensör eşiği, S2 yalnız ET, S3 tahminli (tahmin hatası, gerçekleşen
  değere sabit büyüklükte gürültü eklenerek simüle edilir), S4 asimile edilmiş ikiz.
- **Metrikler:** su (mm, m³), stres günü (Ks<1), sulama olayı sayısı; model doğrulaması: RMSE, yanlılık,
  KGE, NSE. Sıralama: CRITIC (Diakoulaki vd., 1995, *bellekten*).
- **Duyarlılık:** OAT ve Sobol/Morris.
- **Arıza enjeksiyonu (RQ1):** yanlılık, kayma, donma, kopma senaryoları.

### 3.5 Doğrulama

- **Testbed:** model ve sensör arası; saksıda gravimetrik referans örnekler (kurutarak tartma).
  Gerçek bir dijital ikiz döngüsünde kapalı döngü deneyleri (kontrollü kuruma ve sulama).
- **Park ölçeği:** ERA5-Land toprak nemi katmanlarıyla kıyas; İBB yıllık yeşil alan suyu (milyonlarca m³,
  kapsamı belirsiz) ile büyüklük sırası kontrolü (m³/m² × toplam alan). Kurum verisi gelirse sayaç verisiyle.
- Hiçbir doğrulama yoksa sonucu "model çıktısı" olarak etiketle, "ölçüm" diye sunma.

## 4. Kaynaklar ve doğrulama durumu

| Kaynak | Durum |
| --- | --- |
| Koçyiğit, Javadi, Thomson, Pfautsch, Obst (2025). Operational machine learning for park-scale irrigation to support urban cooling. arXiv:2508.11700 | Tam metinden doğrulandı (eşikler, sayılar) |
| Ghadiri, Javadi, Obst, Pfautsch (2024). Data Optimisation of ML Models for Smart Irrigation in Urban Parks. arXiv:2410.02335 | Özet okundu |
| Nasirahmadi ve Hensel (2022). Toward the Next Generation of Digitalization in Agriculture Based on Digital Twin Paradigm. Sensors 22(2):498 | Okundu |
| Obriejetan ve Krexner (2024). Remote sensing-based evapotranspiration modeling for urban green spaces: A case study in Vienna. Urban Climate 58:102192 | Yalnızca özet sayfası, Kc ve SPEI ayrıntıları doğrulanmadı |
| Allen, Pereira, Raes, Smith (1998). FAO Irrigation and Drainage Paper 56 | Bellekten, doğrulanmadı (denklem numaraları kaynaktan alınacak) |
| Kritzinger vd. (2018). Digital Twin in manufacturing: A categorical literature review and classification. IFAC-PapersOnLine | Bellekten, doğrulanmadı |
| Kraskov, Stögbauer, Grassberger (2004). Estimating mutual information. Phys. Rev. E | Bellekten, doğrulanmadı |
| Diakoulaki, Mavrotas, Papayannakis (1995). Determining objective weights in multiple criteria problems: the CRITIC method | Bellekten, doğrulanmadı |
| Cressall vd. (2023), SIMPaCT ilk çalışma (evapotranspirasyon yedek modu) | Yalnızca atıf olarak görüldü |

Bir başka AI aracından gelen özetlerde şu hatalar bulundu; tezde o özetlere değil yukarıdaki kaynaklara atıf yap:
ARIMA eşiği "20" yazılmış (doğrusu 2σ); Kc, NDVI, SPEI ve çim/çayır katsayıları SIMPaCT'e değil Viyana
çalışmasına aittir; "ETa = Kc × ETo" aslında ETc'dir.

## 5. Takvim (Ekim 2026 → Mayıs 2027)

| Dönem | İş |
| --- | --- |
| Ekim–Kasım 2026 | Literatür taraması, RQ'ların danışmanla netleşmesi, çekirdek kütüphane (Faz 1), düğüm masa testi |
| Kasım–Aralık | Testbed kurulumu ve sensör kalibrasyonu, ERA5 ve Sentinel-2 hattı, park verileri |
| Aralık–Şubat | Testbed deneyleri, arıza enjeksiyonu, asimilasyon |
| Şubat–Mart | Strateji simülasyonları, CRITIC, duyarlılık analizi |
| Mart–Mayıs 2027 | Yazım; kurum verisi gelirse ek bölüm. Enstitünün teslim ve jüri takvimi ayrıca teyit edilecek |
