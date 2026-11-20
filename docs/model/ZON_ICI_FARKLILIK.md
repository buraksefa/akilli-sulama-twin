# Zon içi farklılık: güvenlik payı, sensör yerleşimi ve zon boyutu

Durum: 2026-11-20. Kod: `src/twin/sim/heterogeneity.py`, `src/twin/sim/virtual_world.py`
(`sensor_placement`, `BENCHMARKS["ORACLE"]`); testler `tests/test_heterogeneity.py`.

Komutlar:

```
twin heterogeneity --years Y              # varsayılan sanal dünya (sensör arızaları açık)
twin heterogeneity --years Y --no-faults --out outputs/heterogeneity_nofault
```

Her yıl ayrı süreçte koşuldu. Yıl başına 660 koşu sürdü:

- ilk tur (5 paralel süreç): 385–390 s
- ikinci tur (10 paralel süreç): 636–648 s

Çıktılar:

- `outputs/heterogeneity/heterogeneity_{runs,summary}_yildiz_{2020..2024}.csv`
- `outputs/heterogeneity_nofault/…`
- beş yılın ortalaması: `outputs/heterogeneity/summary_2020_2024_both.csv`

**Kaynak etiketi:** `synthetic_world+era5`. Hava gerçek ERA5-Land'dir (2020–2024, 1 Nisan–31 Ekim). Park içi
dağılım, sensörler ve arızalar sanal dünya varsayımıdır. Buradaki sayılar gerçek park ölçümü değildir.

## 1. Soru

Önceki çalışmada zon ortalamasına göre sulayan ikiz, alanın %17–26'sını sezon boyunca strese soktu
(`TAHMIN_ISABETI.md`). Bunun nedeni zon içindeki farklılıktır: aynı zonda sığ köklü, düşük su tutan ya da güneşli
hücreler, zon ortalamasından önce RAW eşiğini aşar. Bu çalışma üç kaldıracı karşılaştırır.

| Kaldıraç | Değerler | Anlamı |
|---|---|---|
| Güvenlik payı `pay` | 0,9 · 0,7 · 0,5 · 0,3 | İkiz kestirilen açığı `pay` · RAW_nominal altında tutar; küçük pay daha erken ve daha çok sular. |
| Sensör yerleşimi | `random` · `critical` | `random`: zon içinde rastgele hücre. `critical`: zonun yaz ortasında RAW'a en önce inen hücresi (en küçük RAW / (Kc_mid · mikroklima)). |
| Zon boyutu | 1×1 · 2×2 · 3×3 · 4×4 blok | Zon = blok × bitki türü. Zon sayısı 4 · 16 · 29 · 41; sensör sayısı 5 · 20 · 36 · 50. |

İkizler:

- **MODEL:** sensör görmez.
- **SENSOR:** zon sensörlerinin ortalaması.
- **ENKF:** model + sensör.

Her sensörlü ayar 10 sensör tohumuyla koşuldu. MODEL tohumdan ve yerleşimden bağımsızdır, bu yüzden bir kez koşuldu.

**Zon kâhini (`ORACLE`, alt sınır):**

- Her hücrenin gerçek açığını ve bugünün gerçek havasını bilir.
- Her zona tek doz verir; doz, o zonun en zorlu hücresini margin 1,0 · RAW altında tutacak kadardır.
- Tanım gereği stressizdir.
- Verilen zon düzeninde stressiz sulamanın en az suyunu verir. Zon içi farklılığın su bedeli budur.
- Bir ikiz değil, kıyas ölçütüdür.

Ölçütler:

- **su:** sezon toplamı (m³), beş yılın ortalaması.
- **stres:** strese giren alan payının sezon ortalaması (%).
- Parantez içindeki [min–maks] aralığı, beş yılın tohum ortalamalarının en küçüğü ve en büyüğüdür.

## 2. Zon kâhini: zonları küçültmenin en fazla getirisi

| Zon düzeni | Zon | Stressiz en az su (m³/sezon) | 1×1'e göre |
|---|---|---|---|
| 1×1 | 4 | 199.223 | – |
| 2×2 | 16 | 184.270 | %−7,5 |
| 3×3 | 29 | 180.097 | %−9,6 |
| 4×4 | 41 | 174.264 | %−12,5 |

Zon içi farklılığın bedeli, kâhin için bile 4 zondan 41 zona geçişte %12,5 sudur. Bu bir üst sınırdır. Bu getiri
yalnız zonun en zorlu hücresinin durumu bilinirse alınabilir.

## 3. Yalnız model (MODEL): güvenlik payı tek başına yetmez

| pay | su (m³) | stres (%) [yıllar] | maks. günlük stres (%) |
|---|---|---|---|
| 0,9 | 159.480 | 19,4 [17,5–22,9] | 40,6 |
| 0,7 | 165.494 | 13,1 [11,5–16,0] | 33,1 |
| 0,5 | 172.859 | 8,1 [6,7–10,5] | 26,3 |
| 0,3 | 185.389 | 3,7 [2,3–5,8] | 16,0 |

- Payı 0,9'dan 0,3'e indirmek suyu %16 artırıyor ve stresi 19,4'ten 3,7'ye düşürüyor; sıfıra indirmiyor.
- 0,3 payında MODEL, 2×2 kâhinden fazla su (185.389 > 184.270 m³) verip yine de alanın %3,7'sini strese sokuyor.
  Su, gereken yere gitmiyor.
- MODEL zon düzeninden etkilenmez: ikiz yalnız nominal parametreleri bilir, küçük zon ona yeni bilgi vermez.

## 4. Sensörler arızasız olsaydı: kritik nokta kazandırıyor

Bu tablo `--no-faults` koşusudur: sensörlerde gürültü (σ 0,02 m³/m³) var, kayma, donma ve veri kaybı yok.

| Zon | İkiz / yerleşim | pay 0,9: su · stres | pay 0,7: su · stres | pay 0,5: su · stres |
|---|---|---|---|---|
| 2×2 | ENKF random | 163.167 · 15,8 | 171.283 · 7,1 | 179.390 · 2,8 |
| 2×2 | ENKF critical | 181.794 · 2,1 | 191.056 · 0,09 | 198.695 · 0,01 |
| 2×2 | SENSOR random | 177.007 · 5,7 | 191.467 · 1,8 | 224.486 · 0,21 |
| 2×2 | SENSOR critical | 199.831 · 0,51 | 217.640 · 0,11 | 264.320 · 0,02 |
| 4×4 | ENKF random | 159.422 · 15,1 | 167.072 · 6,7 | 175.667 · 2,6 |
| 4×4 | ENKF critical | 173.293 · 3,2 | 181.657 · 0,45 | 190.007 · 0,10 |

Kâhine göre en az suyla stresi %1'in altında tutan ayar:

| Zon | Ayar | su (m³) | su / kâhin | stres (%) [yıllar] |
|---|---|---|---|---|
| 1×1 | ENKF critical, pay 0,9 | 197.319 | 0,99 | 0,70 [0,51–0,82] |
| 2×2 | ENKF critical, pay 0,7 | 191.056 | 1,04 | 0,09 [0,06–0,15] |
| 3×3 | ENKF critical, pay 0,7 | 186.284 | 1,04 | 0,53 [0,21–1,09] |
| 4×4 | ENKF critical, pay 0,7 | 181.657 | 1,04 | 0,45 [0,18–0,93] |

- Sensörü zonun kritik hücresine koymak, rastgele yerleşime göre stresi bir büyüklük sırası düşürüyor.
- Bu durumda ENKF, kâhinin yaklaşık %4 fazlasıyla neredeyse stressiz kalıyor. Zon küçüldükçe gereken su da azalıyor:
  191.056 → 181.657 m³ (%−4,9).
- Kritik noktadaki SENSOR, ENKF'den fazla su harcıyor: en kuru hücrenin ölçümü tüm zona uygulanıyor, gürültü de
  doğrudan karara geçiyor.
- Rastgele yerleşimde sonuç, sensörün zonun neresine düştüğüne bağlı. 3×3'te rastgele ENKF (pay 0,9) %22,6
  stresle 2×2 ve 4×4'ten belirgin kötü. Bu, tek bir yerleşim çekilişinin etkisidir (§7).

## 5. Varsayılan sanal dünya (sensör arızaları açık): arıza bir taban oluşturuyor

Senaryodaki arıza payları sensör başına şöyle (varsayım):

| Arıza | Pay |
|---|---|
| Kayma | %15 |
| Donma | %10 |
| Veri kaybı | %10 |

| Zon | İkiz / yerleşim | pay 0,9: su · stres | pay 0,3: su · stres |
|---|---|---|---|
| 1×1 | ENKF critical | 179.566 · 9,8 | 211.757 · 5,6 |
| 2×2 | ENKF critical | 165.637 · 11,2 | 196.624 · 6,6 |
| 4×4 | ENKF critical | 133.704 · 24,6 | 172.929 · 14,6 |
| 2×2 | SENSOR critical | 182.120 · 9,7 | 367.580 · 7,3 |
| 1×1 | SENSOR critical | 198.464 · 8,9 | 476.138 · 6,2 |
| – | MODEL | 159.480 · 19,4 | 185.389 · 3,7 |

- Arızalar açıkken hiçbir sensörlü ayar stresi %5,6'nın altına indiremiyor. Pay küçüldükçe su hızla artıyor:
  kritik noktadaki SENSOR, 1×1 düzende kâhinin 2,4 katı su veriyor.
- Nedeni: yanlış ıslak okuyan (kayan ya da donmuş) bir sensör zonunu kurutuyor; yanlış kuru okuyan sensör, zona her gün
  üst sınıra (35 mm) yakın su verdiriyor.
- **Arıza varken zonları küçültmek kötüleştiriyor:**
  - ENKF critical, pay 0,9: stres 2×2'de %11,2, 4×4'te %24,6.
  - Küçük zonda karar daha az sensöre dayanıyor.
  - Ağaç, çalı ve çiçek zonlarında zon başına tek sensör var; o sensör arızalıysa zonun bütün kararı bozuluyor.
- Bu dünyada en düşük stres, sensörsüz MODEL'in 0,3 payında: %3,7. Arızalı sensör, hiç sensör olmamasından kötü
  olabiliyor.

## 6. Sonuç

1. **Zon içi farklılığın bedeli ölçüldü.** Stressiz sulama için en az su, 4 zondan 41 zona geçişte %12,5 azalıyor
   (kâhin, §2).
2. **Güvenlik payı tek başına yetmiyor.** Nominal modelle stres sıfıra inmiyor; ek su gereken yere gitmiyor (§3).
3. **Sensörün yeri sayısından önemli.** Sensörler sağlamsa, zonun kritik noktasına konmuş bir sensörle model ve
   Kalman birlikte kâhinin yaklaşık %4 fazlası suyla neredeyse stressiz sulama yapıyor (§4). Pratik karşılığı: sensör
   rastgele değil, zonun en çabuk kuruyan yerine (sığ toprak, güneşli kenar) konmalı.
4. **Sensör kalite kontrolü bu getirinin ön koşulu.** Arızalar açıkken kritik yerleşimin ve küçük zonun getirisi
   kayboluyor, hatta tersine dönüyor (§5). Bu, tezin B kolunu (QC, sanal sensör) ve RQ1'i (sensör hatalarının karara
   etkisi) doğrudan destekleyen bir bulgudur. Sıradaki deney, QC kurallarını sanal parka bağlayıp arızalı sensörü
   ayıklayan ikizi aynı tabloda sınamaktır.

## 7. Sınırlılıklar (tezde açıkça yazılmalı)

- **Tek dünya, tek yerleşim:**
  - Tek sanal dünya kullanıldı (`world_seed` 7).
  - Sensör konumları ve arıza türleri de bu tohumla bir kez çekildi.
  - 10 sensör tohumu yalnız gürültüyü ve veri kaybı anlarını değiştirir; konumları ve arıza türlerini değiştirmez.
  - Rastgele yerleşimin yayılımı (3×3 sapması, §4) bu yüzden ölçülmedi. Birden çok dünya ve yerleşim tohumu
    gerekiyor.
- **Kritik noktanın bilindiği varsayıldı.** Gerçekte keşifle (toprak örneği, kuruyan lekelerin gözlemi, termal
  görüntü) bulunur. `critical` sonuçları yerleşimin iyimser ucudur.
- **Varsayımlar:** arıza payları, gürültü ve tüm bitki, toprak ve mikroklima aralıkları sanal dünya varsayımıdır
  (`data/scenarios/yildiz_dunya.json`, `status: assumption`).
- **Başlangıç:** her sezon 1 Nisan'da toprak tarla kapasitesinde başlar.
- **Ayrık çözünürlük:** hücre 10 m'dir. Zon blokları park sınır kutusuna göre bölünür; gerçek vana ve hat düzeni
  değildir.
- **Ölçüt:** stres ölçütü günlük Ks < 1 olan alan payıdır. Stresin şiddeti ve bitkiye etkisi (verim, görsel kalite)
  ölçülmedi.
