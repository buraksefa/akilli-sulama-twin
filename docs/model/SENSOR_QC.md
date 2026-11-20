# Sensör kalite kontrolünün sanal parka bağlanması (B kolu, RQ1)

Durum: 2026-11-20. Kod: `src/twin/qc/online.py` (çevrimiçi QC), `src/twin/sim/virtual_world.py`
(`run_world(..., qc=True)`), eşikler `TwinConfig.sensor_qc`. Testler: `tests/test_sensor_qc_online.py`.

Komutlar: `twin heterogeneity --with-qc --out outputs/sensor_qc --years Y` ve
`twin qc-detection --years Y` (yakalama tablosu). Her yıl ayrı süreçte koşuldu: 1.300 koşu,
749–756 s (5 paralel süreç).

Çıktılar (`outputs/sensor_qc/`):

| Dosya | İçerik |
|---|---|
| `heterogeneity_{runs,summary}_yildiz_{2020..2024}.csv` | Yıl başına koşular ve özetler |
| `summary_2020_2024.csv` | Beş yılın ortalaması |
| `qc_vs_noqc_vs_faultless.csv` | QC'siz, QC'li ve arızasız karşılaştırması |
| `detection_{yıl}.csv` | Sensör başına yakalama zamanı |

**Kaynak etiketi:** `synthetic_world+era5`. Hava gerçek ERA5-Land'dir (2020–2024). Park, sensörler ve arızalar sanal
dünya varsayımıdır. Bu sayılar gerçek park ölçümü değildir.

## 1. Neden

`ZON_ICI_FARKLILIK.md` §5'te arızalı sensörler (sensör başına %15 kayma, %10 donma, %10 veri kaybı; varsayım),
kritik yerleşimin ve küçük zonun getirisini sildi. Sorulan soru şu: kalite kontrol bu getiriyi ne kadar geri kazandırır?

## 2. Kurallar

Saha CSV'leri için yazılmış `qc/rules.py` toplu ve geriye dönük çalışır. Karar anında ise ikiz yalnız o güne kadarki
okumaları görür. Bu yüzden aynı kurallar günlük okumaya uyarlandı ve çevrimiçi hale getirildi.

| # | Kural | Eşik | Durum | Davranış |
|---|---|---|---|---|
| 1 | Fiziksel aralık | VWC 0,0–0,60 | rules.py | okuma reddedilir |
| 2 | Kesinti | > 3 gün okuma yok | SIMPaCT (verified) | yeni okuma gelince geri döner |
| 3 | Eksik oranı | son 10 günde > %50 | SIMPaCT eşiği (verified), pencere varsayım | okuma reddedilir |
| 4 | Donmuş değer | 7 okumada (maks−min)/ort < %1 | SIMPaCT %1 (verified); pencere 7 gün (varsayım) | değer değişince geri döner |
| 5 | Tarla kapasitesi üstü | okuma > θFC_nom + 0,05, art arda 3 gün | varsayım (fiziksel) | sensör kalıcı dışlanır |
| 6 | Doygunluk sonrası referans | dünkü net girdi ≥ ikizin açığı + 5 mm iken okuma > θFC_nom + 0,09 | varsayım (fiziksel) | sensör kalıcı dışlanır |
| 7 | Model–sensör tutarlılığı (kayma) | okuma − açık döngü model farkının 90 günlük EKK eğimi, mutlak değerce > 0,0009 m³/m³/gün (en az 45 okuma) | varsayım; eşik kalibre edildi (§8) | sensör kalıcı dışlanır |

Reddedilen okuma ikize ulaşmaz. Zonda geçerli okuma kalmazsa ikiz su dengesi modeliyle devam eder. Bu, `qc/virtual_sensor.py`'deki model tabanlı yedek sanal sensörün karşılığıdır.

**İki düzeltme testte ortaya çıktı (varsayım etiketli):**

- **Donmuş değer penceresi:** SIMPaCT'in 120 saatlik penceresi saatlik veride yaklaşık 120 örnek içerir. Günlükte bu
  5 örneğe iner. Sağlam ve gürültülü (σ 0,02) bir sensörde 5 okuma rastlantıyla %1'in altına düştü ve yanlış alarm
  verdi. Pencere 7 güne uzatıldı.
- **Doygunluk kontrolü payı:** İlk denenen pay 0,05 idi ve sağlam bir sensörü dışladı. Tek okumalık karar için pay
  0,09'a çıkarıldı: θFC yayılımı 0,03 + 3σ gürültü.

SIMPaCT'in sıçrama kuralı kullanılmadı. Günlük okumada yağış ve sulama gerçek sıçrama üretir.

## 3. Yakalama başarısı

Kapsam: 5 yıl × 4 zon düzeni × 2 yerleşim × 2 ikiz × 2 pay × 10 tohum. Sayılar sensör-sezon birimindedir.

| Gerçek arıza | Sensör-sezon | Yakalanan | Gecikme ortancası (gün) | Gecikme %90 (gün) |
|---|---|---|---|---|
| Sağlam | 25.200 | **0** (yanlış alarm yok) | – | – |
| Donma (20 gün) | 5.600 | %100 | 6 | 6 |
| Kayma (+0,001 m³/m³/gün) | 9.600 | %100 | 134 | 179 |
| Veri kaybı (%20 gün) | 4.000 | %36 | 126 | 180 |

- **Donma:** pencere dolar dolmaz (6. gün) yakalanıyor.
- **Kayma:** her zaman yakalanıyor ama çok geç. Kural 5, sapma ancak ~0,14–0,19 m³/m³'e çıktığında tetikleniyor.
  Kural 6 için yazın bir referans günü yok: JIT sulama toprağı hiç tarla kapasitesine getirmiyor, toprağı
  dolduracak yağış da çoğunlukla sonbaharda geliyor.
- **Veri kaybı:** zaten boş okuma ürettiği için zararı küçük. Yakalanan %36, rastlantısal 3 günlük kesintilerdir.

## 4. Karara etkisi

Aşağıdaki ENKF ikizi sonuçları beş yılın ortalamasıdır. "Kapanan pay", arızanın yarattığı stres farkının QC ile
kapanan oranıdır:

```
(stres QC'siz − stres QC'li) / (stres QC'siz − stres arızasız)
```

| Zon | Yerleşim | Pay | Su QC'siz → QC'li (m³) | Stres QC'siz → QC'li (%) | Arızasız stres (%) | Kapanan pay |
|---|---|---|---|---|---|---|
| 1×1 | kritik | 0,7 | 190.108 → 190.986 | 8,4 → 7,8 | 0,05 | 0,08 |
| 2×2 | kritik | 0,7 | 175.290 → 177.934 | 8,8 → 7,3 | 0,09 | 0,17 |
| 2×2 | rastgele | 0,3 | 178.868 → 188.570 | 8,6 → 3,6 | 0,84 | 0,65 |
| 3×3 | kritik | 0,7 | 156.339 → 170.958 | 15,2 → 8,2 | 0,53 | 0,47 |
| 3×3 | kritik | 0,3 | 185.469 → 200.258 | 8,8 → 3,1 | 0,00 | 0,65 |
| 4×4 | kritik | 0,7 | 144.668 → 156.944 | 21,2 → 14,9 | 0,45 | 0,31 |
| 4×4 | kritik | 0,3 | 172.929 → 188.389 | 14,6 → 7,2 | 0,00 | 0,51 |

Tam tablo `qc_vs_noqc_vs_faultless.csv` dosyasında. Tüm 64 sensörlü ayarda kapanan payın dağılımı:

| Ölçüt | Değer |
|---|---|
| Ortalama | 0,37 |
| Ortanca | 0,36 |
| En küçük | 0,04 |
| En büyük | 1,02 |

- **QC her ayarda stresi düşürüyor; su %0,3–10,7 artıyor.** Su artışının nedeni, yanlış ıslak okuyan sensörün
  dışlanınca zonun gerçekten sulanmaya başlamasıdır.
- **En büyük getiri küçük zonlarda.** Burada zon başına tek sensör var ve arıza zonun bütün kararını bozuyordu.
  Örneğin 3×3, kritik yerleşim, pay 0,7'de stres 15,2'den 8,2'ye iniyor. QC, ZON_ICI_FARKLILIK §5'teki "küçük zon
  arızayla kötüleşir" etkisini kısmen düzeltiyor.
- **QC, arızasız düzeye yaklaşamıyor.** Arızanın yarattığı stres farkının ortalama yalnız üçte biri kapanıyor.
  Kalan farkın ana nedeni kayan sensörün geç yakalanmasıdır (§3).
- **Hâlâ en ucuz düşük stres sensörsüz modelden geliyor.** Sensörsüz MODEL, pay 0,3'te 185.389 m³ su ve %3,7 stres
  veriyor. QC'li en iyi sensörlü ayarlar:

  | Ayar | Su (m³) | Stres (%) | Yıllar (stres %) |
  |---|---|---|---|
  | 2×2 rastgele ENKF, pay 0,3 | 188.570 | 3,6 | 0,3–6,5 |
  | 3×3 kritik ENKF, pay 0,3 | 200.258 | 3,1 | 1,2–4,1 |

  Bu sanal dünyada QC'li sensörler, sensörsüz modele karşı stresi en fazla 0,6 puan düşürüyor ve bunu daha çok
  suyla yapıyor.

> §3–§4 kural 1–6 içindir (kayma testi yokken). Kural 7'nin eklenmesiyle değişen sonuçlar §8'dedir.

## 5. Sonuç (RQ1 için, kural 1–6)

1. SIMPaCT kuralları günlük okumaya uyarlanınca donmuş sensörü 6 günde ve yanlış alarmsız yakalıyor.
2. **Kayan sensör asıl sorun.** Yavaş kayma, aralık ve donma kurallarına görünmüyor. Fiziksel tutarlılık kuralları
   (tarla kapasitesi üstü, doygunluk sonrası referans) kaymayı ancak sezonun ikinci yarısında yakalıyor.
3. QC, arızanın karara etkisinin ortalama üçte birini geri alıyor. Kalan kısım kaymanın geç fark edilmesinden
   geliyor. Tezde "QC yetmez, kaymaya özgü yöntem gerekir" diye raporlanmalı.

**Önerilen sonraki adımlar:**

- **Model–sensör tutarlılık testi:** yapıldı, bkz. §8.
- **Planlı referans sulaması:** birkaç haftada bir bir zonu tarla kapasitesine kadar sulayıp kural 6'ya kalibrasyon
  anı yaratmak. Ek su maliyeti ölçülmeli.
- **Sahada:** iki sensörlü zon ya da periyodik elle kalibrasyon. Maliyet karşılaştırması yapılmalı.

## 6. Ekranda

Kenar çubuğunda **Sensör kalite kontrolü (QC)** anahtarı var; açık gelir. Zon kartındaki sensör tablosu her sensör
için şunları gösterir:

- son okuma,
- QC kararı (ör. "geçti", "donmuş değer", "tarla kapasitesi üstü"),
- sanal dünyadaki gerçek arıza (ikiz bunu bilmez).

## 7. Sınırlılıklar

- Arıza payları, kayma hızı (0,001 m³/m³/gün, yalnız ıslak yöne) ve gürültü varsayımdır. Kuru yöne kayma
  denenmedi; kural 5 ve 6 onu yakalayamaz.
- Tek sanal dünya kullanıldı (`world_seed` 7). Sensör konumları ve arıza türleri bir kez çekildi
  (ZON_ICI_FARKLILIK §7).
- θFC_nominal, ikizin bildiği tek değerdir (0,28). Sahada sensör konumunda ölçülürse kural 5 ve 6 daha dar payla
  ve daha erken çalışabilir.

## 8. Model–sensör tutarlılık testi (kural 7, kayma)

Durum: 2026-11-21. Kod: `OnlineSensorQC._update_drift` (`src/twin/qc/online.py`); açık döngü referansı
`run_world` içinde (`theta_openloop` sütunu); eşikler `TwinConfig.sensor_qc.drift_*`. Testler:
`tests/test_sensor_qc_online.py` (doğrusal kayma yakalanır, sabit sapma yakalanmaz, referans yoksa test atlanır).

### 8.1 Fikir

EnKF yeniliği (innovation) kaymayı göremez: ikiz sensörü özümsediği için önsel kestirim de sensörle birlikte kayar.
Bu yüzden ikiz, zon başına **sensörü hiç görmeyen bir açık döngü su dengesi modeli** yürütür. Model nominal
parametrelerle, uygulanan dozlar ve gözlenen havayla ilerler. Her sensör için şu fark izlenir:

```
r_t = θ_okuma,t − θ_açık döngü,t
```

- Zon içi farklılıkta θFC farkı **sabit** bir r üretir. Kc·mikroklima ya da Zr farkı ise sınırlı bir eğilim üretir:
  hücre tarla kapasitesine ya da strese dayanınca durur.
- Kayma ise **doğrusal ve sınırsız** büyür.

Test, r'nin son 90 gündeki EKK eğimine bakar. Eğim mutlak değerce eşiği aşarsa sensör kalıcı olarak dışlanır.
Test iki yönlüdür, ama kuru yöne kayma denenmedi.

### 8.2 İstatistik seçimi ve eşik kalibrasyonu

Betikler `tools/drift_calibration/` altında. Tablo `outputs/sensor_qc_drift/statistic_comparison.csv` dosyasında.

- **Koşu altkümesi:** 4 zon düzeni × 2 strateji × 4 tohum, pay 0,7, 4.440 sensör-sezon. Kayma testi kapalıydı.
- **Eşik:** 2020–2021'deki sağlam sensörlerin sezon içi en büyük |istatistik| değerinin %99 (ya da %100) dilimi.
- **Değerlendirme:** bağımsız olarak 2022–2024'te.

| İstatistik | Pencere | Eşik dilimi | Eşik | Yanlış alarm (2022–24) | Kayma yakalama | Gecikme ortanca / %90 (gün) |
|---|---|---|---|---|---|---|
| EKK eğimi | 60 | %99 | 0,00111 | %4,0 | %100 | 60 / 106 |
| EKK eğimi | 60 | %100 | 0,00154 | %0 | %20 | 112 / 156 |
| **EKK eğimi** | **90** | **%99** | **0,00090** | **%0,5** | **%100** | **44 / 76** |
| EKK eğimi | 90 | %100 | 0,00134 | %0 | %23 | 64 / 143 |
| Theil–Sen | 60 | %99 | 0,00115 | %4,0 | %99,7 | 70 / 121 |
| EKK + birikimli ETc ortak değişkeni | 60 | %99 | 0,0254 | %2,5 | %1,7 | 117 / 125 |
| EKK + birikimli ETc ortak değişkeni | 90 | %99 | 0,0096 | %15,7 | %13,9 | 143 / 149 |
| EKK + birikimli ETc ve girdi ortak değişkenleri | 90 | %99 | 0,0128 | %11,8 | %12,7 | 123 / 146 |

- **ET ortak değişkeni işe yaramadı.** Birikimli ETc pencere içinde zamanla neredeyse doğrusal ilerliyor; bu yüzden
  kayma ile Kc farkı istatistiksel olarak ayrılamıyor (eşdoğrusallık). Tek sensörle bu ikisi temelde
  birbirine karışır; 90 günlük pencere, farklılığın sınırlı olmasından yararlanarak ayrımı sağlıyor.
- **Seçim:** 90 gün, EKK eğimi, eşik 0,0009 (`assumption`, sanal dünyaya özgü).
- **İlk deneme:** 60 gün ve 0,0007 eşiğiyle yapıldı. Sentetik test havasında (ETo 4–7 mm, 90 gün) sağlam çalı
  sensörlerini dışladı. Bu sensörlerin Kc'si nominalden ~%13 düşüktü. Kalibrasyon bu yüzden gerekti.

### 8.3 Yakalama başarısı (tam deney, 5 yıl, 44.400 sensör-sezon)

`twin qc-detection --years Y --out outputs/sensor_qc_drift`: yıl başına 446–447 s (10 paralel süreç).

| Gerçek arıza | Sensör-sezon | Yakalanan | Gecikme ortancası (gün) | Gecikme %90 (gün) | Kural 1–6 ile gecikme ortancası (§3) |
|---|---|---|---|---|---|
| Sağlam | 25.200 | **125 (%0,50)** yanlış alarm | – | – | 0 yanlış alarm |
| Donma | 5.600 | %100 | 6 | 6 | 6 |
| Kayma | 9.600 | %100 | **44** | **82** | 134 / 179 |
| Veri kaybı | 4.000 | %36 | 125 | 180 | 126 |

- **Kaymanın %93'ü kural 7 ile yakalandı.** Gecikme ortancası 44 gün; bu, en az 45 okuma koşulunun izin verdiği
  en erken gündür.
- **Bedel: sağlam sensörde %0,5 yanlış alarm.** Yıllara göre: 2020 %0,36, 2021 %1,15, 2022 %0,46, 2023 %0,06,
  2024 %0,46. Kalibrasyon yılı 2021'de oran en yüksek. Kalibrasyonda sezon içi en büyük değerin %99 dilimi
  alındığı için bu beklenen bir sonuç.

### 8.4 Karara etkisi (ENKF, 5 yılın ortalaması)

`twin heterogeneity --with-qc --years Y --out outputs/sensor_qc_drift`: yıl başına 1.300 koşu, 1.174–1.193 s
(10 paralel süreç). Tam tablo `outputs/sensor_qc_drift/qc_drift_comparison.csv` dosyasında. QC'siz satırlar §4'teki
koşularla birebir aynı (fark 0).

| Zon | Yerleşim | Pay | Stres: QC'siz / QC 1–6 / QC 1–7 / arızasız (%) | Su: QC 1–7 / arızasız (m³) |
|---|---|---|---|---|
| 1×1 | kritik | 0,7 | 8,4 / 7,8 / **3,1** / 0,05 | 199.466 / 207.224 |
| 2×2 | kritik | 0,7 | 8,8 / 7,3 / **1,6** / 0,09 | 187.987 / 191.056 |
| 2×2 | rastgele | 0,3 | 8,6 / 3,6 / **1,0** / 0,84 | 192.533 / 192.253 |
| 3×3 | kritik | 0,7 | 15,2 / 8,2 / **2,9** / 0,53 | 182.358 / 186.284 |
| 4×4 | kritik | 0,5 | 18,5 / 11,4 / **2,7** / 0,10 | 185.884 / 190.007 |
| 4×4 | rastgele | 0,5 | 20,3 / 12,0 / **3,0** / 2,63 | 177.994 / 175.667 |

Tüm 64 sensörlü ayarda kapanan pay (§4 tanımı):

| Ölçüt | QC 1–6 | QC 1–7 |
|---|---|---|
| Ortalama | 0,37 | **0,84** |
| Ortanca | 0,36 | 0,83 |
| En küçük | 0,04 | 0,35 |
| En büyük | 1,02 | 1,44 |

- **Kapanan pay 1'i aşabiliyor.** Bu, rastgele yerleşimde (3×3, 4×4) QC'li stresin arızasız sensörden bile düşük
  olduğu anlamına geliyor. Nedeni şu: kural 7, Kc'si nominalden düşük, yani zondan daha ıslak kalan **sağlam ama
  temsil gücü zayıf** sensörleri de dışlıyor (%0,5 yanlış alarm). Ardından ikiz modele düşüyor ve daha çok suluyor
  (örneğin 3×3 rastgele, pay 0,7: 165.437 m³'e karşı arızasız 161.445 m³). Bu kazanç arıza yakalamadan değil,
  temsil gücü zayıf sensörü elemekten geliyor.

### 8.5 Sensörsüz modelle karşılaştırma

§4'teki sonuç tersine döndü: kayma testiyle QC'li sensörlü ikiz, sensörsüz modeli geçiyor.

| Ayar | Su (m³) | Stres (%) | Yıllara göre stres (%), 2020–2024 |
|---|---|---|---|
| Sensörsüz MODEL, pay 0,3 | 185.389 | 3,7 | 5,8 / 2,3 / 3,7 / 3,0 / 3,7 |
| 2×2 kritik ENKF + QC 1–7, pay 0,7 | 187.987 (+%1,4) | **1,6** | 2,9 / 1,0 / 2,2 / 0,9 / 1,1 |
| 4×4 kritik ENKF + QC 1–7, pay 0,5 | 185.884 (+%0,3) | **2,7** | 3,8 / 1,9 / 3,3 / 2,2 / 2,4 |
| 4×4 rastgele ENKF + QC 1–7, pay 0,5 | 177.994 (−%4,0) | **3,0** | 4,7 / 1,7 / 3,5 / 2,3 / 2,5 |

- Yaklaşık aynı suyla stres 3,7'den 1,6'ya iniyor. 2×2 kritik ENKF, pay 0,7 ayarı **beş yılın her birinde**
  sensörsüz modelden daha az stres veriyor. Sezonluk su farkı −%1,8 ile +%3,6 arasında.
- Kalibrasyonla değerlendirme ayrılsa da (2020–21 / 2022–24) bulgu yönü her iki dönemde aynı.

### 8.6 Sonuç (RQ1 güncellemesi)

1. SIMPaCT kuralları donmayı yakalıyor, ama kaymaya karşı yetersiz. Kayma, açık döngü modelle tutarlılık testiyle
   ortanca 44 günde yakalanıyor (önce 134 gün).
2. Bunun bedeli sağlam sensörde %0,5 yanlış alarm. Yanlış alarm verilen sensörler çoğunlukla zonu temsil etmeyen
   (Kc'si düşük) hücrelerde ve bu sanal dünyada dışlanmaları kararı iyileştiriyor.
3. Kayma testiyle sensörlü ikiz, sensörsüz modele karşı aynı suda stresi yaklaşık yarıya indiriyor. §5'teki
   "QC yetmez" sonucu yalnız SIMPaCT tipi kurallar için geçerli.

### 8.7 Sınırlılıklar (kural 7)

- **Eşik aynı sanal dünyadan kalibre edildi** (yıllar ayrı, dünya aynı). Sahada eşik, sağlam sensör verisiyle yeniden
  kalibre edilmeli.
- **Kayma sezon başında başlıyor ve hızı sabit** (0,001/gün). Geç başlayan ya da daha yavaş kayma daha geç
  yakalanır. 0,0009 eşiğinin altındaki kayma hızları hiç yakalanamaz.
- **Kuru yöne kayma denenmedi.**
- **Açık döngü model hatası:** model, uygulanan doz ve gözlenen havayla sürülüyor. Sahada sayaç ya da yağış ölçümü
  hatalıysa referans da bozulur ve eşik buna göre gevşetilmeli.
- **Tahmin modu:** `plan_from_forecast` bugünkü okumada kayma testine yeni nokta eklemiyor. Pencere bir gün eksik
  kalıyor; geçmiş günlerde test çalışıyor.
