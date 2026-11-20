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

## 5. Sonuç (RQ1 için)

1. SIMPaCT kuralları günlük okumaya uyarlanınca donmuş sensörü 6 günde ve yanlış alarmsız yakalıyor.
2. **Kayan sensör asıl sorun.** Yavaş kayma, aralık ve donma kurallarına görünmüyor. Fiziksel tutarlılık kuralları
   (tarla kapasitesi üstü, doygunluk sonrası referans) kaymayı ancak sezonun ikinci yarısında yakalıyor.
3. QC, arızanın karara etkisinin ortalama üçte birini geri alıyor. Kalan kısım kaymanın geç fark edilmesinden
   geliyor. Tezde "QC yetmez, kaymaya özgü yöntem gerekir" diye raporlanmalı.

**Önerilen sonraki adımlar (henüz yapılmadı):**

- **Model–sensör tutarlılık testi:** EnKF yeniliklerinin (innovation) kayan ortalamasında sistematik eğilim aramak.
  Zon içi farklılığın yarattığı sabit farkı kaymadan ayırmak gerekecek.
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
