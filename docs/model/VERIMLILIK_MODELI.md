# Su kullanım verimliliği: matematiksel model ve teorik alt sınır

Durum: taslak, 2026-11-13; varsayılan config 2026-11-19'da FAO-56'ya düzeltildi (bkz. §10). Kod: `src/twin/sim/efficiency.py`, testler: `tests/test_efficiency.py`,
komut: `twin efficiency --years 2020-2024`. Bu belgedeki tüm sayılar
`outputs/efficiency/*.csv` dosyalarından üretildi. Hava verisi **source: era5** (ERA5-Land, Yıldız
hücresi, 2020-2024, 1 Nisan-31 Ekim, 214 gün). Toprak ve sistem parametreleri **varsayım**.

## 1. Neden bu çalışma

"Akıllı sulama su tasarrufu sağlar" iddiası, bir kıyas noktası olmadan yalnızca stratejileri birbirine
karşı sıralar. Bu belge iki şey ekler:

1. **Mutlak bir kıyas noktası:** belirli bir model ve hava serisi altında, bitkiyi hiç strese
   sokmadan sezonu geçirmek için gereken **en az** sulama suyu W\*. Hiçbir strateji, stressiz kaldığı
   sürece W\*'dan az su kullanamaz. Bir stratejinin verimsizliği W − W\* olarak ölçülür.
2. **Verimsizliğin fiziksel ayrıştırması:** fazla suyun nereye gittiği (derin sızma, depolama, bitki
   tüketimi) su dengesinden kapalı biçimde hesaplanır.

Bunlar veri ve IoT kurulumu gerektirmez; yalnızca FAO-56 kova modelini ve ERA5 verisini kullanır.
Sensör geldiğinde aynı çerçeve, "sensörün su tasarrufuna katkısı" sorusunu ölçmek için kullanılır.

## 2. Model (durum-uzay biçimi)

Günlük adım t = 1..n. Durum: gün sonu kök bölgesi tükenmesi x_t = Dr_t [mm]. Kontrol: brüt sulama
u_t [mm]. Dışsal girdiler: ETo_t, Kc_t, P_t.

```
TAW = 1000 (θFC − θWP) Zr,     RAW = p · TAW                         (FAO-56 Bölüm 8)
Ks(x) = 1                        x ≤ RAW
      = (TAW − x) / ((1 − p) TAW) x > RAW
RO_t  = max(0, P_t − P_ro)                                            (yüzey akışı, varsayım)
y_t   = x_{t−1} − (P_t − RO_t) − η u_t + Ks(x_{t−1}) Kc_t ETo_t
x_t   = min(TAW, max(0, y_t)),     DP_t = max(0, −y_t)                (derin sızma)
```

Varsayılan değerler (`src/twin/config.py`, 2026-11-19'dan itibaren): θFC = 0,28, θWP = 0,14,
Zr = 0,5 m → TAW = 70 mm, p = 0,40 → RAW = 28 mm; Kc 0,90/0,95/0,95; η = 0,75; P_ro = 25 mm;
günlük brüt doz üst sınırı u_max = 35 mm. Zr, p ve Kc FAO-56 serin iklim çimi (`verified`);
θFC, θWP, η, P_ro ve u_max `assumption` veya `to_verify`. §3-§6'daki sayılar **v1 (eski config:
Zr = 0,30 m, p = 0,50, Kc 0,85/0,95/0,85 → TAW = 42 mm, RAW = 21 mm)** ile üretildi;
güncel sonuçlar §10'dadır.

Sezon su bütçesi (kapanış denklemi), her politika için özdeş olarak sağlanır:

```
Σ(P − RO) + η Σu = Σ ETa + Σ DP + (x_0 − x_n)                        (1)
```

Testte tüm stratejiler için kapanış hatası < 1e-6 mm (`test_water_balance_closes_for_all_strategies`).

## 3. Problem P1: stressiz sezon için en az su

Eşik D ∈ (0, RAW] seçilir (D = RAW tam stressizlik; D < RAW "güvenlik payı").

```
W*(D) = min Σ u_t   öyle ki   x_t ≤ D  (t = 1..n),   0 ≤ u_t ≤ u_max
```

x_{t−1} ≤ D ≤ RAW olduğundan Ks = 1, yani ETa = ETc = Kc·ETo: kısıt bölgesinde model **doğrusaldır**.
Kâhin tam zamanında (JIT) politika:

```
u*_t = max(0, x*_{t−1} − (P_t − RO_t) + Kc_t ETo_t − D) / η
```

Yani yalnızca gün sonu tükenme D'yi aşacaksa, tam olarak D'ye indirecek kadar sulama. Bu politika o
günün ETo ve yağışını bilir; gerçekte uygulanamaz, yalnızca **alt sınır** olarak kullanılır.

**Önerme 1 (JIT optimaldir).** u_max kısıtı JIT'te bağlayıcı değilse, P1'in her uygulanabilir
çözümü π için Σu^π ≥ Σu\*.

*İspat (tümevarım).* a_t = Kc_t ETo_t − (P_t − RO_t), net sulama i_t = η u_t, birikimli net sulama
C_t olsun. Her uygulanabilir π için x^π_t = x^π_{t−1} + a_t − i^π_t + d^π_t yazılabilir;
burada d^π_t ≥ 0 drenajdır ve 0 ≤ x^π_t ≤ D. (Fiziksel model d'yi yalnız x = 0'da serbest bırakır;
ispat d'nin işaretinden başka bir şey kullanmaz.) JIT için x\*_t = min(D, max(0, x\*_{t−1} + a_t)).
Hipotez H_t: Δ_t := C^π_t − C\*_t ≥ max(0, x\*_t − x^π_t). H_0 eşitlikle sağlanır.

- JIT sularsa (x\*_t = D, i\*_t = x\*_{t−1} + a_t − D):
  i^π_t − i\*_t = (x^π_{t−1} − x\*_{t−1}) + d^π_t + (D − x^π_t), dolayısıyla
  Δ_t ≥ Δ_{t−1} − (x\*_{t−1} − x^π_{t−1}) + (D − x^π_t) ≥ D − x^π_t = x\*_t − x^π_t ≥ 0.
- JIT sulamazsa: Δ_t = Δ_{t−1} + i^π_t ≥ 0. x\*_t = 0 ise H_t açıktır; değilse
  x\*_t − x^π_t = (x\*_{t−1} − x^π_{t−1}) + i^π_t − d^π_t ≤ Δ_{t−1} + i^π_t = Δ_t.

Böylece Δ_n ≥ 0. η sabit olduğundan net ve brüt toplam aynı sırayı verir. ∎

Kanıt yalnızca d ≥ 0 kullandığı için sonuç, drenajı serbest bırakan **doğrusal programlama
gevşetmesi** için de geçerlidir. Bu yüzden `minimum_irrigation_lp` (HiGHS) ile hesaplanan LP en iyi
değeri, JIT toplamına eşit çıkmalıdır. Bu eşitlik her sezon için ayrı bir **sayısal sertifikadır**
(aşağıdaki tablo v1 eski config; güncel config için §10):

| sezon | JIT W\* (mm) | LP alt sınırı (mm) | fark (mm) |
|---|---|---|---|
| 2020 | 784.48 | 784.48 | -1.1e-13 |
| 2021 | 597.1 | 597.1 | -1.1e-13 |
| 2022 | 680.8 | 680.8 | 0.0e+00 |
| 2023 | 706.61 | 706.61 | -1.1e-13 |
| 2024 | 743.58 | 743.58 | 0.0e+00 |

JIT'in en büyük günlük brüt dozu 8,4-9,7 mm oldu (u_max = 35 mm bağlayıcı olmadı, Önerme 1'in koşulu
sağlandı). Yorum notu: Önerme 1'deki yapı, [0, D] aralığında iki yönlü yansıtılmış bir yürüyüşe
(Skorohod eşlemesi) benzer; bu bağlantı literatürden **doğrulanmadı**, ispat ona dayanmıyor.

**Sonuç 1 (kuru tutmanın değeri).** D₁ < D₂ ise P1(D₁)'in uygulanabilir kümesi P1(D₂)'ninkinin alt
kümesidir, dolayısıyla W\*(D₂) ≤ W\*(D₁). Fiziksel anlamı: toprağı izin verilen en kuru sınırda
tutmak, yağışı tutacak boş hacim bırakır ve derin sızmayı azaltır.

ERA5 2020-2024 üzerinde stressiz en az brüt su [mm], v1 eski config (`allowed_depletion_sweep_yildiz_v1_eski_config.csv`):

| sezon | D=0,25·RAW | D=0,5·RAW | D=0,75·RAW | D=1,0·RAW |
|---|---|---|---|---|
| 2020 | 844.0 | 807.4 | 791.5 | 784.5 |
| 2021 | 707.1 | 650.2 | 612.1 | 597.1 |
| 2022 | 757.7 | 711.2 | 694.8 | 680.8 |
| 2023 | 787.3 | 747.4 | 722.0 | 706.6 |
| 2024 | 836.2 | 797.0 | 764.6 | 743.6 |

Aynı hava serisinde güvenlik payı (D = 0,25·RAW) en az suyu yıla göre 59,6-110,0 mm artırıyor.

## 4. Önerme 2: fazla suyun ayrıştırması

Aynı hava ve x_0 için (1)'i bir strateji S ile kâhin için yazıp çıkarınca:

```
W_S − W* = [ ΔΣETa + ΔΣDP + Δ(x_0 − x_n) ] / η                      (2)
```

Stressiz iki politika için ΔΣETa = 0'dır; fazla su, fazladan derin sızma ve depolama farkıdır.
Stresli bir politikada ΔΣETa < 0'dır: daha az su, bitkinin daha az tüketmesinden gelir ve bu bir
**tasarruf değil, açıktır**. `decompose_excess` bu ayrımı yapar; özdeşlik testte doğrulanıyor.

## 5. Verimlilik göstergeleri (tanımlar)

| gösterge | tanım | not |
|---|---|---|
| W − W\* | kâhine göre fazla brüt su [mm] | birincil verimsizlik ölçüsü |
| tasarruf (S0'a göre) | 100·(W_S0 − W_S)/W_S0 | yalnız eşit stres düzeyinde anlamlı |
| bağıl ET açığı | 1 − ΣETa/ΣETc | bitki suyu karşılanma derecesinin tamamlayanı |
| tüketim payı | ΣETa / (ΣP + Σu) | toplam su girdisinin bitkiye giden payı |
| stres günü | #{t : Ks_t < 1} | CRITIC ölçütüyle aynı |

Bu tanımlar FAO-56 su dengesi terimlerinden türetildi. Literatürdeki "irrigation efficiency /
irrigation adequacy" tanımlarıyla (ör. Burt vd. 1997, ASCE) karşılaştırma **yapılmadı**, kaynak
kontrolü bekliyor.

## 6. Sonuçlar (v1, eski config): ERA5 2020-2024, Yıldız, mevcut stratejiler (source: era5)

`outputs/efficiency/efficiency_yildiz_v1_eski_config.csv`; brüt mm; S1, S3 ve S4 tek rastgele tohumla (42) koştu.

| sezon | strateji | W | W − W\* | DP payı | ETa payı | S0'a göre tasarruf % | stres günü | bağıl ET açığı |
|---|---|---|---|---|---|---|---|---|
| 2020 | ORACLE | 784.5 | 0.0 | 0.0 | 0.0 | 9.2 | 0 | 0.0 |
| 2020 | S0 | 864.0 | 79.5 | 239.0 | -159.5 | 0.0 | 79 | 0.153 |
| 2020 | S1 | 892.1 | 107.6 | 128.8 | -21.2 | -3.2 | 19 | 0.02 |
| 2020 | S2 | 780.3 | -4.2 | 13.8 | -18.0 | 9.7 | 24 | 0.017 |
| 2020 | S3 | 780.3 | -4.2 | 13.8 | -18.0 | 9.7 | 24 | 0.017 |
| 2020 | S4 | 792.7 | 8.3 | 21.0 | -12.7 | 8.2 | 23 | 0.012 |
| 2021 | ORACLE | 597.1 | 0.0 | 0.0 | 0.0 | 30.9 | 0 | 0.0 |
| 2021 | S0 | 864.0 | 266.9 | 338.5 | -98.4 | 0.0 | 51 | 0.099 |
| 2021 | S1 | 755.0 | 157.9 | 159.2 | -12.0 | 12.6 | 13 | 0.012 |
| 2021 | S2 | 658.8 | 61.7 | 66.8 | -15.8 | 23.7 | 21 | 0.016 |
| 2021 | S3 | 664.4 | 67.3 | 75.5 | -18.8 | 23.1 | 23 | 0.019 |
| 2021 | S4 | 653.1 | 56.0 | 55.1 | -9.8 | 24.4 | 21 | 0.01 |
| 2022 | ORACLE | 680.8 | 0.0 | 0.0 | 0.0 | 21.2 | 0 | 0.0 |
| 2022 | S0 | 864.0 | 183.2 | 239.2 | -84.0 | 0.0 | 41 | 0.083 |
| 2022 | S1 | 751.8 | 71.0 | 82.0 | -20.9 | 13.0 | 16 | 0.021 |
| 2022 | S2 | 718.5 | 37.7 | 38.4 | -16.7 | 16.8 | 23 | 0.016 |
| 2022 | S3 | 727.2 | 46.4 | 49.1 | -18.7 | 15.8 | 25 | 0.018 |
| 2022 | S4 | 713.3 | 32.5 | 27.3 | -8.8 | 17.4 | 14 | 0.009 |
| 2023 | ORACLE | 706.6 | 0.0 | 0.0 | 0.0 | 18.2 | 0 | 0.0 |
| 2023 | S0 | 864.0 | 157.4 | 270.7 | -141.3 | 0.0 | 74 | 0.14 |
| 2023 | S1 | 829.6 | 123.0 | 137.7 | -22.8 | 4.0 | 18 | 0.023 |
| 2023 | S2 | 739.5 | 32.8 | 23.8 | -15.5 | 14.4 | 23 | 0.015 |
| 2023 | S3 | 740.8 | 34.2 | 25.0 | -15.4 | 14.3 | 24 | 0.015 |
| 2023 | S4 | 736.2 | 29.6 | 13.4 | -9.8 | 14.8 | 18 | 0.01 |
| 2024 | ORACLE | 743.6 | 0.0 | 0.0 | 0.0 | 13.9 | 0 | 0.0 |
| 2024 | S0 | 864.0 | 120.4 | 290.7 | -198.2 | 0.0 | 81 | 0.186 |
| 2024 | S1 | 901.6 | 158.1 | 160.8 | -15.3 | -4.4 | 16 | 0.014 |
| 2024 | S2 | 819.0 | 75.4 | 89.2 | -14.4 | 5.2 | 27 | 0.014 |
| 2024 | S3 | 788.2 | 44.6 | 58.7 | -14.7 | 8.8 | 28 | 0.014 |
| 2024 | S4 | 778.5 | 34.9 | 28.0 | -14.5 | 9.9 | 21 | 0.014 |

"DP payı" ve "ETa payı", (2)'deki terimlerin brüt karşılığıdır; depolama terimi CSV'de ayrı sütundadır.

### Bulgular (dürüstçe)

1. **Mevcut S0-S4 stratejilerinin hiçbiri stressiz değil** (13-81 stres günü). Bu yüzden
   "S0'a göre tasarruf %" sütunu tek başına verimlilik artışı olarak sunulamaz; stratejiler farklı
   stres düzeylerinde. 2020'de S2 ve S3 kâhinden 4,2 mm **az** su kullandı, ama 24 stres günü
   pahasına (ETa payı −18,0 mm). Bu tasarruf değil, açıktır.
2. S1-S4 tetikleyicisi "gün başı Dr ≥ RAW". Bu kural tanım gereği tükenmenin RAW'ı aştığı ertesi
   gün Ks < 1 üretir; stres günleri tasarımdan geliyor. Bağıl ET açığı küçük (%0,9-2,3), ama sıfır değil.
3. S0 (3 günde bir 12 mm, sezonda 864 mm) her yıl kâhinden 79-267 mm fazla su kullanıyor **ve** aynı
   zamanda 41-81 gün stres üretiyor. Fazla suyun brüt karşılığı 239-338 mm derin sızma; bitki
   tüketimindeki açık −84 ile −198 mm arasında. Sabit takvim hem israf ediyor hem susuz bırakıyor.
4. S1 (gürültülü sensör eşiği) 2020 ve 2024'te S0'dan **daha fazla** su kullandı. Bunun olası nedeni:
   σ_obs = 0,02 m³/m³ gürültü, Zr = 0,3 m'de ±6 mm Dr belirsizliği demek. Bu da RAW = 21 mm'lik
   eşiğe göre büyük; yanlış tetiklemelere ve tarla kapasitesine kadar doldurmaya yol açıyor.
   Bu yorum tek tohuma dayanıyor, çoklu tohumla **doğrulanmadı**.
5. Stresli stratejiler içinde S4, 2021-2024'te en küçük DP payını verdi. 2020'de S2 ve S3'ün DP
   payı daha küçüktü. Tek tohum, sınırlı genelleme.
6. Gerçek yıllar arası fark büyük: W\* 597,1 mm (2021, yağış 311,1 mm) ile 784,5 mm (2020, yağış
   253,6 mm) arasında. Sentetik üretecin dar yıllar arası farkı bu değişkenliği temsil etmiyordu.

## 7. Sınırlılıklar

- W\* bir **model içi** alt sınırdır. Toprak parametreleri, η ve Kc tablosu varsayım; W\*'ın mutlak
  değeri bunlara duyarlı (duyarlılık analizi henüz bu çerçeveye bağlanmadı).
- ERA5-Land hücresi kıyı/Boğaz karışık hücresi; ETo yanlılığı olabilir.
- Kâhin aynı günün yağışını ve ETo'sunu bilir. Gerçekleştirilebilir en iyi politikayla W\* arasındaki
  fark ("bilginin değeri") henüz ölçülmedi.
- Tek kova, tek bölge; alan içi heterojenlik, sulama düzgünlüğü (DU) ve rüzgâr kaybı η içinde topaklandı.
- Stresli bölgede (Ks < 1) model doğrusal değil. Açık sulama (deficit irrigation) ile su-stres
  ödünleşimi P1 kapsamında değil.

## 8. Sıradaki matematiksel adımlar (öneri, onay bekliyor)

1. **Öngörülü tetikleyici (uygulanabilir JIT yaklaşımı):** "bugün Dr ≥ RAW ise doldur" yerine
   "yarının tahmini Dr'si D'yi aşacaksa yalnız eksik kadar ver". ETo tahmini ERA5 iklimsel ortalamasıyla
   ya da kalıcılıkla yapılır, yağış bilinmez. Böylece stressiz ve W\*'a yakın, uygulanabilir bir
   strateji (S5) elde edilir; kâhinle farkı "tahmin bilgisinin değeri" olur.
2. **Su-stres Pareto cephesi:** P2 = min Σu + λ·Σ(1 − Ks). Stresli bölgedeki doğrusal olmama nedeniyle
   x_t ızgarası üzerinde dinamik programlama ile çözülür. Her strateji bu cepheye uzaklığıyla
   değerlendirilir. Bu, eşit olmayan stres düzeylerindeki karşılaştırma sorununu çözer.
3. **Belirsizlik altında sağlamlık:** W\*'ın θFC, θWP, Zr, p, η ve Kc dağılımlarına göre Sobol
   duyarlılığı. Hangi parametrenin ölçülmesi gerektiği sorusuna (RQ3) doğrudan girdi verir.
4. **Çoklu tohum ve güven aralığı:** S1, S3 ve S4 için en az 30 tohum (CLAUDE.md §5, madde 4).

## 9. Bitki tipine göre hesap (2026-11-13)

Kod: `VEGETATION_PROFILES` ve `config_for_vegetation()` (`src/twin/config.py`),
`park_zone_requirement()` (`src/twin/sim/efficiency.py`), komut
`twin efficiency --vegetation <profil>`. Toprak (θFC, θWP), η ve yüzey akışı eşiği temel
yapılandırmadan gelir; profil yalnız Kc evrelerini, Zr ve p'yi değiştirir.

### 9.1 Doğrulanmış profiller (birincil kaynak)

FAO-56 sayfaları 2026-11-13'te okundu: Tablo 12 http://www.fao.org/4/x0490e/x0490e0b.htm,
Tablo 22 http://www.fao.org/4/x0490e/x0490e0e.htm.

| profil | Kc ini | Kc mid | Kc end | Zr (m) | p | kaynak satırı |
|---|---|---|---|---|---|---|
| turf_cool_season | 0.90 | 0.95 | 0.95 | 0.5 (aralık 0.5-1.0) | 0.40 | Turf grass - cool season |
| turf_warm_season | 0.80 | 0.85 | 0.85 | 0.5 (aralık 0.5-1.0) | 0.50 | Turf grass - warm season |

Zr için aralığın alt sınırı alındı. Tablo 22, dipnot 1'e göre küçük değerler sulama planlaması için
önerilir. FAO-56 Tablo 12 dipnot 15: serin iklim çimleri bluegrass, ryegrass ve fescue'dur.
Referans tablondaki Lolium perenne + Festuca arundinacea karışımı bu sınıfa girer; `lawn` zonları
`turf_cool_season`'a eşlendi. Ay → evre eşlemesi (Nisan-Mayıs ini, Haziran-Ağustos mid,
Eylül-Ekim end) FAO'dan değil, koddan gelen bir **varsayım**dır.

### 9.2 Bulgu: mevcut varsayılan config kendi kaynağıyla uyuşmuyor

`CropParameters` ve `SoilParameters` alanları kaynak olarak FAO-56 Tablo 12/22'yi gösteriyor,
ama değerler tabloyla aynı değil:

| parametre | config değeri | config'in gösterdiği kaynak | FAO-56'daki değer |
|---|---|---|---|
| kc_initial | 0.85 | Table 12 cool-season turf | 0.90 |
| kc_end | 0.85 | Table 12 late season | 0.95 |
| root_depth_m | 0.30 | "Table 22 turfgrass 0.20-0.40 m" | 0.5-1.0 m |
| p_depletion | 0.50 | "Table 22 turfgrass p = 0.50" | 0.40 (cool) / 0.50 (warm) |

**Çözüldü (2026-11-19):** Burak'ın onayıyla varsayılan config FAO-56 serin iklim çimi değerlerine
düzeltildi (§10). Not: Zr = 0,30 m kent çimi için gerçekçi olabilir,
ama o zaman kaynağı "varsayım" olarak etiketlenmeli, FAO-56 değil.

### 9.3 Sonuç: kâhin W\* bitki profiline göre (ERA5 2020-2024, Yıldız, source: era5, brüt mm)

| sezon | v1 eski config | turf_cool_season (= güncel varsayılan) | turf_warm_season |
|---|---|---|---|
| 2020 | 784.5 | 812.5 | 689.7 |
| 2021 | 597.1 | 623.1 | 506.3 |
| 2022 | 680.8 | 701.2 | 586.4 |
| 2023 | 706.6 | 719.9 | 599.3 |
| 2024 | 743.6 | 754.1 | 628.2 |

- Kâhin = LP eşitliği her iki profilde de geçerli (en büyük fark 3,4e-13 mm). JIT'in en büyük
  günlük dozu 9,68 mm, yani u_max bağlayıcı değil. Kapanış hatası 2,1e-13 mm'nin altında.
- Serin iklim çimi, sıcak iklim çiminden yıla göre 114,8-125,9 mm daha fazla en az su gerektiriyor.
- Stres günleri profile göre değişiyor. Örneğin S4: varsayılanda 14-23, cool season'da 10-18,
  warm season'da 6-19. S0-S4'ün hiçbiri iki profilde de stressiz değil; §6'daki ana bulgu geçerli.

### 9.4 Henüz yapılamayanlar (kaynak bekliyor)

- **Ağaç, çalı ve mevsimlik çiçek profilleri eklenmedi.** Kent peyzajı için standart yöntem WUCOLS
  tür faktörü ve Peyzaj Katsayısı Yöntemi'dir (K_L = k_s · k_d · k_mc; Costello vd.). Bu kaynakların
  sayfaları (ccuh.ucdavis.edu) erişimde 403 verdi, değerler doğrulanamadı. Bellekten değer yazılmadı.
  `config_for_vegetation("tree")` bilinçli olarak hata verir. Profili olmayan zon
  `park_zone_requirement` çıktısında `no_verified_profile` olarak görünür.
- **Park bileşimi bilinmiyor.** `parks.py` her park için tek bir `lawn` zonu üretiyor (alanın %60'ı,
  `assumption`). Yıldız Korusu büyük ölçüde ağaçlık olduğundan bu varsayımla hesaplanan m³ değerleri
  (`zones_yildiz.csv`, ör. 2020: 190.003,5 m³) **tez sonucu olarak kullanılamaz**. Zon alanları İBB
  yanıtı ya da uydu/harita maskesiyle belirlenene kadar yalnız mm/sezon değerleri anlamlıdır.
- `Besiktas_Sulama_Bitki_Referans_Tablosu` (Excel): kaynak satırında "İBB saha verileri 2023-2024"
  yazıyor, ama hazırlayan ve danışman alanları şablon olarak kalmış ve tablo kapsam dışı Fethi Paşa'yı
  içeriyor. "Günlük su ihtiyacı (L/m²)" havadan bağımsız sabit bir sayıdır; ETo tabanlı FAO-56
  yaklaşımıyla doğrudan birleştirilemez. Kaynağı doğrulanana kadar bu tablodan modele değer alınmadı.

## 10. Config düzeltmesi sonrası sonuçlar (2026-11-19, source: era5)

Değişiklik: `SoilParameters.root_depth_m` 0,30 → 0,5 m, `p_depletion` 0,50 → 0,40,
`CropParameters.kc_initial` 0,85 → 0,90, `kc_end` 0,85 → 0,95 (kc_mid 0,95 aynı). Kaynak:
FAO-56 Tablo 12/22 serin iklim çimi, durum `verified`. Sonuç: TAW 42 → 70 mm, RAW 21 → 28 mm.
Varsayılan config artık `turf_cool_season` profiliyle birebir aynı (test:
`test_default_config_matches_fao56_cool_season_turf`). Eski çıktılar `*_v1_eski_config.csv`
adıyla saklandı.

Sertifika: kâhin ile LP arasındaki en büyük fark 3.4e-13 mm. JIT'in en büyük günlük dozu
9.68 mm; u_max bağlayıcı değil, Önerme 1'in koşulu sağlanıyor.

### 10.1 Stratejiler ve kâhin (`efficiency_yildiz.csv`, brüt mm, tek tohum 42)

| sezon | strateji | W | W − W\* | DP payı | ETa payı | S0'a göre tasarruf % | stres günü | bağıl ET açığı |
|---|---|---|---|---|---|---|---|---|
| 2020 | ORACLE | 812.5 | 0.0 | 0.0 | 0.0 | 6.0 | 0 | 0.0 |
| 2020 | S0 | 864.0 | 51.5 | 209.4 | -157.9 | 0.0 | 88 | 0.146 |
| 2020 | S1 | 910.0 | 97.5 | 105.6 | -8.1 | -5.3 | 10 | 0.008 |
| 2020 | S2 | 840.0 | 27.5 | 35.1 | -7.6 | 2.8 | 24 | 0.007 |
| 2020 | S3 | 840.0 | 27.5 | 35.1 | -7.6 | 2.8 | 24 | 0.007 |
| 2020 | S4 | 840.0 | 27.5 | 32.3 | -4.7 | 2.8 | 18 | 0.004 |
| 2021 | ORACLE | 623.1 | 0.0 | 0.0 | 0.0 | 27.9 | 0 | 0.0 |
| 2021 | S0 | 864.0 | 240.9 | 294.1 | -89.6 | 0.0 | 61 | 0.087 |
| 2021 | S1 | 770.0 | 146.9 | 129.6 | -3.2 | 10.9 | 6 | 0.003 |
| 2021 | S2 | 665.0 | 41.9 | 30.6 | -5.5 | 23.0 | 19 | 0.005 |
| 2021 | S3 | 665.0 | 41.9 | 31.2 | -6.2 | 23.0 | 20 | 0.006 |
| 2021 | S4 | 665.0 | 41.9 | 28.7 | -2.5 | 23.0 | 10 | 0.002 |
| 2022 | ORACLE | 701.2 | 0.0 | 0.0 | 0.0 | 18.8 | 0 | 0.0 |
| 2022 | S0 | 864.0 | 162.8 | 199.2 | -73.8 | 0.0 | 51 | 0.07 |
| 2022 | S1 | 805.0 | 103.8 | 91.4 | -4.2 | 6.8 | 9 | 0.004 |
| 2022 | S2 | 735.0 | 33.8 | 18.5 | -5.1 | 14.9 | 21 | 0.005 |
| 2022 | S3 | 735.0 | 33.8 | 18.6 | -5.2 | 14.9 | 23 | 0.005 |
| 2022 | S4 | 735.0 | 33.8 | 14.0 | -4.6 | 14.9 | 14 | 0.004 |
| 2023 | ORACLE | 719.9 | 0.0 | 0.0 | 0.0 | 16.7 | 0 | 0.0 |
| 2023 | S0 | 864.0 | 144.1 | 245.1 | -138.4 | 0.0 | 79 | 0.132 |
| 2023 | S1 | 875.0 | 155.1 | 127.0 | -5.4 | -1.3 | 12 | 0.005 |
| 2023 | S2 | 735.0 | 15.1 | 19.7 | -6.4 | 14.9 | 21 | 0.006 |
| 2023 | S3 | 735.0 | 15.1 | 19.7 | -6.4 | 14.9 | 21 | 0.006 |
| 2023 | S4 | 735.0 | 15.1 | 17.8 | -4.4 | 14.9 | 13 | 0.004 |
| 2024 | ORACLE | 754.1 | 0.0 | 0.0 | 0.0 | 12.7 | 0 | 0.0 |
| 2024 | S0 | 864.0 | 109.9 | 254.4 | -181.9 | 0.0 | 85 | 0.166 |
| 2024 | S1 | 945.0 | 190.9 | 183.9 | -13.0 | -9.4 | 15 | 0.012 |
| 2024 | S2 | 805.0 | 50.9 | 35.0 | -11.0 | 6.8 | 23 | 0.01 |
| 2024 | S3 | 770.0 | 15.9 | 22.3 | -11.5 | 10.9 | 25 | 0.01 |
| 2024 | S4 | 805.0 | 50.9 | 29.2 | -5.2 | 6.8 | 14 | 0.005 |

### 10.2 İzin verilen tükenmeye göre en az su (`allowed_depletion_sweep_yildiz.csv`, brüt mm)

| sezon | D=0,25·RAW | D=0,5·RAW | D=0,75·RAW | D=1,0·RAW |
|---|---|---|---|---|
| 2020 | 865.2 | 831.1 | 821.8 | 812.5 |
| 2021 | 719.9 | 657.1 | 632.5 | 623.1 |
| 2022 | 773.2 | 732.0 | 713.4 | 701.2 |
| 2023 | 804.1 | 763.4 | 738.6 | 719.9 |
| 2024 | 854.7 | 807.0 | 777.4 | 754.1 |

### 10.3 Bulgular

1. Kâhin W\* 623.1-812.5 mm. D = 0,25·RAW güvenlik payı, en az suyu
   52.7-100.5 mm artırıyor.
2. S0 her yıl kâhinden 51.5-240.9 mm fazla su kullanıyor ve
   51-88 stres günü üretiyor. §6'daki "hem israf hem stres" bulgusu korunuyor.
3. S0-S4'ün hiçbiri stressiz değil (6-88 stres günü).
4. **Yeni yapay etki: 35 mm üst sınırı artık S1-S4'ü belirliyor.** RAW = 28 mm'de tetikleme dozu
   Dr/η ≥ 28/0,75 ≈ 37,3 mm, yani u_max = 35 mm'nin üstünde. 2020 ve 2024 kontrolünde S1-S4'ün
   **her** sulama olayı 35 mm'de kesildi. Sonuç: S2, S3 ve S4 çoğu yıl aynı toplamı veriyor
   (ör. 2020'de üçü de 840 mm = 24 × 35). Farklar yalnız sulamanın zamanlamasından geliyor.
   Bu, stratejilerin değil, `max_gross_dose_mm` varsayımının (CLAUDE.md §3, `assumption`) sonucu.
   u_max'ın kaynağı netleşmeden S1-S4 karşılaştırması tez sonucu olarak kullanılmamalı.
   Kâhin bu sınırdan etkilenmiyor.

## 11. Öğrenilmiş politika (S6) ve öğrenmesiz taban (S5) (2026-11-19, source: era5)

Kod: `src/twin/sim/learned_policy.py`, testler: `tests/test_learned_policy.py`, komut:
`twin learned-policy --margins 1.0,0.9,0.8` (duvar saati 5:02.77 total; `outputs/learned_policy/run_log.txt`).
Çıktı: `outputs/learned_policy/loyo_yildiz.csv`.

### 11.1 Kurulum

- **Bilgi kümesi (nedensel):** dünkü ve önceki günlerin gerçekleşmiş ETo/yağışı (gecikme 1, 3 ve 7
  günlük özetler), Dr_(t−1), aya bağlı Kc, gün-yıl (sin/cos). Bugünün ETo'su ve yağışı **kullanılmaz**
  (sızıntı testi: `test_policies_do_not_see_todays_weather`). Dr_(t−1) gerçek durumdur, yani S2 ile aynı
  bilgi; sensörlü/asimilasyonlu sürüm ayrı bir iştir.
- **S5, kalıcılık JIT (öğrenmesiz taban):** bugünkü ETc ≈ Kc·ETo_(t−1), yağış = 0 varsayımıyla
  u = max(0, Dr_(t−1) + Kc·ETo_(t−1) − D)/η.
- **S6, öğrenilmiş politika:** kâhin dozunu (hedef D) özelliklerden tahmin eden
  `HistGradientBoostingRegressor` (sklearn 1.9.1, varsayılan hiperparametreler, early_stopping kapalı,
  tohum 0). DAgger ile 3 tur eğitildi: ilk turda kâhin yürür, sonraki turlarda öğrenilen politika yürür
  ve ziyaret ettiği durumlar kâhinle etiketlenir. DAgger kaynağı: Ross, Gordon & Bagnell 2011
  (bellekten, **doğrulanmadı**).
- **Değerlendirme:** yıl-dışı-bırak. Her test yılında model diğer 4 yılla eğitilir, test yılı eğitime
  girmez (`test_leave_one_year_out_never_trains_on_test_year`).
- **Güvenlik payı:** S5 ve S6 aynı hedefle çalışır: D = f·RAW, f ∈ {1,0; 0,9; 0,8}. W\* her zaman tam
  RAW hedefli kâhindir (alt sınır).

### 11.2 Özet (5 test yılı; brüt mm)

| D/RAW | strateji | ort. W | ort. W − W\* | W − W\* min / maks | stres günü | ort. Σ(1−Ks) | ort. DP |
|---|---|---|---|---|---|---|---|
| 1.0 | S2 | 756.0 | 33.8 | 15.1 / 50.9 | 19-24 | 1.092 | 54.3 |
| 1.0 | S4 | 756.0 | 33.8 | 15.1 / 50.9 | 10-18 | 0.682 | 51.8 |
| 1.0 | S5 | 721.4 | -0.8 | -2.5 / 0.7 | 41-54 | 0.555 | 35.1 |
| 1.0 | S6 | 711.1 | -11.1 | -15.7 / -7.8 | 73-95 | 2.177 | 35.0 |
| 0.9 | S2 | 756.0 | 33.8 | 15.1 / 50.9 | 19-24 | 1.092 | 54.3 |
| 0.9 | S4 | 756.0 | 33.8 | 15.1 / 50.9 | 10-18 | 0.682 | 51.8 |
| 0.9 | S5 | 731.4 | 9.2 | 5.9 / 15.1 | 0-0 | 0.0 | 37.7 |
| 0.9 | S6 | 730.9 | 8.7 | 6.2 / 12.5 | 0-4 | 0.035 | 37.7 |
| 0.8 | S2 | 756.0 | 33.8 | 15.1 / 50.9 | 19-24 | 1.092 | 54.3 |
| 0.8 | S4 | 756.0 | 33.8 | 15.1 / 50.9 | 10-18 | 0.682 | 51.8 |
| 0.8 | S5 | 738.4 | 16.2 | 9.6 / 26.3 | 0-0 | 0.0 | 40.7 |
| 0.8 | S6 | 738.0 | 15.8 | 9.7 / 24.3 | 0-0 | 0.0 | 40.8 |

S2 ve S4'ün f'ye bağlı parametresi yok; aynı satırlar her f için tekrar ediyor. İkisi de 35 mm
üst sınırından etkileniyor (§10.3).

### 11.3 Yıl bazında, D = 0,9·RAW

| sezon | strateji | W | W − W\* | stres günü | Σ(1−Ks) |
|---|---|---|---|---|---|
| 2020 | ORACLE | 812.5 | 0.0 | 0 | 0.0 |
| 2020 | S2 | 840.0 | 27.5 | 24 | 1.2 |
| 2020 | S4 | 840.0 | 27.5 | 18 | 0.798 |
| 2020 | S5 | 818.4 | 5.9 | 0 | 0.0 |
| 2020 | S6 | 818.7 | 6.2 | 4 | 0.062 |
| 2021 | ORACLE | 623.1 | 0.0 | 0 | 0.0 |
| 2021 | S2 | 665.0 | 41.9 | 19 | 0.878 |
| 2021 | S4 | 665.0 | 41.9 | 10 | 0.434 |
| 2021 | S5 | 629.3 | 6.2 | 0 | 0.0 |
| 2021 | S6 | 629.4 | 6.2 | 1 | 0.013 |
| 2022 | ORACLE | 701.2 | 0.0 | 0 | 0.0 |
| 2022 | S2 | 735.0 | 33.8 | 21 | 0.831 |
| 2022 | S4 | 735.0 | 33.8 | 14 | 0.714 |
| 2022 | S5 | 707.8 | 6.6 | 0 | 0.0 |
| 2022 | S6 | 708.7 | 7.5 | 4 | 0.099 |
| 2023 | ORACLE | 719.9 | 0.0 | 0 | 0.0 |
| 2023 | S2 | 735.0 | 15.1 | 21 | 1.009 |
| 2023 | S4 | 735.0 | 15.1 | 13 | 0.708 |
| 2023 | S5 | 732.3 | 12.4 | 0 | 0.0 |
| 2023 | S6 | 731.0 | 11.1 | 0 | 0.0 |
| 2024 | ORACLE | 754.1 | 0.0 | 0 | 0.0 |
| 2024 | S2 | 805.0 | 50.9 | 23 | 1.542 |
| 2024 | S4 | 805.0 | 50.9 | 14 | 0.757 |
| 2024 | S5 | 769.2 | 15.1 | 0 | 0.0 |
| 2024 | S6 | 766.7 | 12.5 | 1 | 0.003 |

### 11.4 Bulgular

1. **Uygulanabilir, stressiz ve kâhine yakın bir politika var.** D = 0,9·RAW'da S5 beş yılın
   hepsinde 0 stres günüyle kâhinden ortalama 9.2 mm
   (5.9-15.1 mm) fazla su kullandı. Aynı yıllarda
   S4 ortalama 33.8 mm fazla su kullandı ve 10-18 stres günü üretti.
   Fark (S4 − S5) ortalama 24.6 mm/sezon ve bu fark stresi de sıfırlayarak elde ediliyor.
   Bu iyileşme ML'den değil, JIT yapısından (dolumu tam tarla kapasitesine değil, eşiğin hemen altına
   yapmak) ve güvenlik payından geliyor.
2. **ML, öğrenmesiz tabana anlamlı bir şey eklemedi (negatif sonuç).** Ortalama fazla su farkı
   (S5 − S6): f = 0,9'da 0.5 mm, f = 0,8'de 0.5 mm. f = 0,9'da S6 bazı yıllarda
   0-4 stres günü üretti, S5 hiç üretmedi. f = 1,0'da S6, kâhinden **az** su
   kullanıyor ama bu açık demek: 73-95 stres günü,
   ortalama Σ(1−Ks) 2.177. Kare kayıplı regresyon belirsizlikte ortalamaya
   çekiyor ve dozu küçük tahmin ediyor.
3. **Neden ML katkı vermiyor:** kâhin dozu, ETc_t − (P_t − RO_t) üzerinden bugünün havasına bağlı.
   Nedensel özelliklerle ETc_t'nin tahmin edilebilir kısmını kalıcılık zaten yakalıyor. Yağışı
   geçmiş günlerden tahmin etmek mümkün değil. Öğrenilecek ek sinyal, ancak yeni bilgi
   (hava tahmini, sensör) eklendiğinde ortaya çıkabilir.
4. f = 1,0'daki S5 stres günleri (41-54) çok hafif: bağıl ET açığı ≤ %0,4. JIT, toprağı tam eşikte
   tuttuğu için küçük tahmin hataları Ks'yi 1'in biraz altına itiyor. Stres günü sayısı bu yüzden
   tek başına yanıltıcı; şiddet ölçüsü Σ(1−Ks) tabloya eklendi.

### 11.5 Sınırlılıklar

- Tek model tohumu (0); S1, S3 ve S4 tek gürültü tohumuyla (42) koştu. 5 yıl, test başına 4 eğitim yılı.
- Hiperparametre araması yapılmadı. Kuantil kayıp gibi asimetrik bir kayıp, az sulamayı daha çok
  cezalandırarak S6'yı iyileştirebilir; denenmedi.
- Politikalar gerçek Dr'yi görüyor. Gerçekte Dr, sensör ve asimilasyonla gürültülü kestirilir;
  S5/S6'nın gürültülü durumla davranışı ölçülmedi.
- Toprak (θFC, θWP), η, Kc ay eşlemesi ve u_max varsayım; ERA5 kıyı hücresi yanlılığı (§7) geçerli.

## 12. Gürültülü durumla S5: durum kestiricileri ve model hatası (2026-11-19, source: era5)

Kod: `EstimatedPersistenceJIT` ve `noisy_state_experiment` (`src/twin/sim/learned_policy.py`), testler:
`tests/test_state_estimation.py`, komut `twin noisy-state --seeds 10`. Çıktı:
`outputs/noisy_state/noisy_state_yildiz.csv`, `outputs/noisy_state/run_log.txt`.
Süre (deney): 163.2 s, 1300 sezon koşusu; duvar saati 2:46.90 total.

### 12.1 Kurulum

- S5 aynı doz kuralını kullanır: u = max(0, Dr̂_(t−1) + Kc_t·b·ETo_(t−1) − D)/η. Değişen tek şey Dr̂'dir:
  - **true:** gerçek Dr_(t−1) (§11'deki S5 ile özdeş; test `test_true_estimator_equals_s5`).
  - **sensor:** yalnız sensör. Motorun gözlemi θ_obs = θ_true + N(0; 0,02 m³/m³) ve bu, Zr = 0,5 m'de
    Dr'de σ ≈ 10 mm demek. Dr̂ = clip(1000·Zr·(θFC − θ_obs), 0, TAW).
  - **openloop:** sensörsüz model; kendi Dr̂'sini dünkü b·ETo, Kc, yağış ve kendi dünkü dozuyla su
    dengesi adımıyla ilerletir.
  - **enkf:** 40 üyeli EnKF. Önce **dünkü** hava ve dünkü dozla forecast_step, sonra bugünkü sensör
    gözlemiyle (Dr_(t−1)'i ölçer) analysis_step. Bugünün havası hiçbir kestiricide kullanılmaz
    (test `test_estimators_do_not_see_todays_weather`).
- **Model hatası senaryosu:** b = ikizin ETo'su / gerçek ETo ∈ {0,9; 1,0; 1,1}. Gerçek su dengesi
  ERA5 ETo'suyla, ikiz b·ETo ile çalışır. b, ERA5 kıyı hücresi yanlılığını temsil eden bir
  **varsayım** senaryosudur, ölçülmüş değildir.
- Güvenlik payı D = f·RAW, f ∈ {0,9; 0,8}. Tohum 0-9: motorun sensör gürültüsünü ve EnKF topluluğunu
  belirler. W\* = tam RAW hedefli, gerçek hava ve b = 1 ile kâhin.
- Referans: aynı tohumlarla S2 (gerçek Dr) ve S4 (mevcut EnKF uygulaması). S4'ün b senaryosu yok
  (gerçek havayla çalışır, bkz. §12.4).
- Sayılar: önce her tohumda 5 yılın (2020-2024) ortalaması alındı, sonra tohumlar arası ortalama ±
  standart sapma (n = 10). "%95 aralık", 10 tohumun 2,5 ve 97,5 yüzdelikleridir. n = 10 ile bu
  pratikte en küçük ve en büyük değere yakındır; parametrik bir güven aralığı değildir.

### 12.2 Sonuçlar (yıllık ortalama, brüt mm)

| strateji | b | D/RAW | W − W\* (mm) | %95 aralık W − W\* | stres günü/yıl | Σ(1−Ks)/yıl | DP (mm) | kestirim RMSE (mm) | kestirim yanlılığı (mm) |
|---|---|---|---|---|---|---|---|---|---|
| S2 | - | - | 33.8 ± 0.0 | 33.8 / 33.8 | 21.6 ± 0.0 | 1.09 ± 0.00 | 54.3 ± 0.0 | - | - |
| S4 | - | - | 29.6 ± 8.9 | 14.4 / 40.8 | 17.0 ± 3.7 | 0.96 ± 0.30 | 49.6 ± 2.5 | - | - |
| S5-true | 0.9 | 0.9 | 8.6 ± 0.0 | 8.6 / 8.6 | 0.0 ± 0.0 | 0.00 ± 0.00 | 37.4 ± 0.0 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| S5-true | 0.9 | 0.8 | 15.5 ± 0.0 | 15.5 / 15.5 | 0.0 ± 0.0 | 0.00 ± 0.00 | 40.3 ± 0.0 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| S5-true | 1.0 | 0.9 | 9.2 ± 0.0 | 9.2 / 9.2 | 0.0 ± 0.0 | 0.00 ± 0.00 | 37.7 ± 0.0 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| S5-true | 1.0 | 0.8 | 16.2 ± 0.0 | 16.2 / 16.2 | 0.0 ± 0.0 | 0.00 ± 0.00 | 40.7 ± 0.0 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| S5-true | 1.1 | 0.9 | 9.8 ± 0.0 | 9.8 / 9.8 | 0.0 ± 0.0 | 0.00 ± 0.00 | 38.0 ± 0.0 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| S5-true | 1.1 | 0.8 | 17.0 ± 0.0 | 17.0 / 17.0 | 0.0 ± 0.0 | 0.00 ± 0.00 | 41.2 ± 0.0 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| S5-sensor | 0.9 | 0.9 | 38.6 ± 6.1 | 30.9 / 48.7 | 12.7 ± 3.3 | 0.92 ± 0.27 | 58.1 ± 3.2 | 9.03 ± 0.35 | 0.74 ± 0.68 |
| S5-sensor | 0.9 | 0.8 | 60.8 ± 6.0 | 52.6 / 70.4 | 6.0 ± 1.8 | 0.36 ± 0.17 | 70.2 ± 4.7 | 8.82 ± 0.34 | 0.94 ± 0.71 |
| S5-sensor | 1.0 | 0.9 | 41.3 ± 6.0 | 33.5 / 51.2 | 11.2 ± 2.8 | 0.78 ± 0.25 | 59.3 ± 3.4 | 9.00 ± 0.35 | 0.76 ± 0.69 |
| S5-sensor | 1.0 | 0.8 | 63.8 ± 6.0 | 55.3 / 73.3 | 5.1 ± 1.8 | 0.29 ± 0.15 | 72.0 ± 4.9 | 8.79 ± 0.34 | 0.97 ± 0.71 |
| S5-sensor | 1.1 | 0.9 | 44.0 ± 5.9 | 36.2 / 53.5 | 9.7 ± 2.3 | 0.67 ± 0.23 | 60.6 ± 3.6 | 8.97 ± 0.35 | 0.79 ± 0.69 |
| S5-sensor | 1.1 | 0.8 | 66.9 ± 6.0 | 58.2 / 76.1 | 4.1 ± 1.6 | 0.24 ± 0.14 | 73.9 ± 5.0 | 8.76 ± 0.34 | 1.00 ± 0.72 |
| S5-openloop | 0.9 | 0.9 | -93.0 ± 0.0 | -93.0 / -93.0 | 143.2 ± 0.0 | 14.65 ± 0.00 | 32.7 ± 0.0 | 7.41 ± 0.00 | -6.92 ± 0.00 |
| S5-openloop | 0.9 | 0.8 | -85.5 ± 0.0 | -85.5 / -85.5 | 134.8 ± 0.0 | 13.37 ± 0.00 | 32.9 ± 0.0 | 9.45 ± 0.00 | -8.74 ± 0.00 |
| S5-openloop | 1.0 | 0.9 | 9.2 ± 0.0 | 9.2 / 9.2 | 0.0 ± 0.0 | 0.00 ± 0.00 | 37.7 ± 0.0 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| S5-openloop | 1.0 | 0.8 | 16.2 ± 0.0 | 16.2 / 16.2 | 0.0 ± 0.0 | 0.00 ± 0.00 | 40.7 ± 0.0 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| S5-openloop | 1.1 | 0.9 | 111.8 ± 0.0 | 111.8 / 111.8 | 0.0 ± 0.0 | 0.00 ± 0.00 | 106.9 ± 0.0 | 14.92 ± 0.00 | 12.71 ± 0.00 |
| S5-openloop | 1.1 | 0.8 | 119.2 ± 0.0 | 119.2 / 119.2 | 0.0 ± 0.0 | 0.00 ± 0.00 | 110.9 ± 0.0 | 12.97 ± 0.00 | 11.00 ± 0.00 |
| S5-enkf | 0.9 | 0.9 | -19.1 ± 6.9 | -28.6 / -7.1 | 84.2 ± 8.4 | 3.49 ± 0.71 | 35.2 ± 1.0 | 3.49 ± 0.36 | -2.77 ± 0.38 |
| S5-enkf | 0.9 | 0.8 | 3.7 ± 5.1 | -4.5 / 12.2 | 28.1 ± 8.2 | 0.82 ± 0.37 | 37.6 ± 1.1 | 3.79 ± 0.41 | -2.98 ± 0.43 |
| S5-enkf | 1.0 | 0.9 | 7.8 ± 4.0 | 0.9 / 13.6 | 9.2 ± 6.3 | 0.23 ± 0.20 | 38.1 ± 1.0 | 1.91 ± 0.22 | 0.12 ± 0.49 |
| S5-enkf | 1.0 | 0.8 | 16.8 ± 3.1 | 11.6 / 21.4 | 0.7 ± 1.0 | 0.01 ± 0.02 | 41.6 ± 0.9 | 1.98 ± 0.22 | 0.23 ± 0.51 |
| S5-enkf | 1.1 | 0.9 | 17.7 ± 2.9 | 12.9 / 22.3 | 0.3 ± 0.6 | 0.01 ± 0.02 | 42.7 ± 0.9 | 4.06 ± 0.40 | 3.36 ± 0.54 |
| S5-enkf | 1.1 | 0.8 | 27.5 ± 3.1 | 22.3 / 32.5 | 0.0 ± 0.0 | 0.00 ± 0.00 | 47.8 ± 1.1 | 3.99 ± 0.38 | 3.28 ± 0.52 |

### 12.3 Bulgular

1. **Yalnız sensör hem israf hem stres üretiyor.** Kestirim RMSE'si 9.00 ± 0.35 mm,
   yani RAW = 28 mm'nin üçte biri. b = 1'de f = 0,9 ile kâhinden 41.3 ± 6.0 mm fazla
   su ve 11.2 ± 2.8 stres günü; f = 0,8 ile fazla su 63.8 ± 6.0 mm'ye
   çıkıyor, stres günü yine sıfıra inmiyor (5.1 ± 1.8). Gürültülü tek bir ölçüme
   doğrudan bağlı JIT, gürültüyü doza aktarıyor. Bu, §6'daki S1 bulgusunu (gürültülü sensör eşiği
   çok su harcıyor) tekrarlıyor ve genelliyor.
2. **Açık döngü model, ETo yanlılığına karşı kırılgan.** b = 1'de kusursuz (9.2 ± 0.0 mm,
   0 stres), ama bu yalnız ikizin modeli "gerçek"le aynı olduğu için böyle; doğal olarak iyimser.
   b = 0,9'da hata birikip kâhinden -93.0 ± 0.0 mm **az** su ve
   143.2 ± 0.0 stres günü (açık); b = 1,1'de 111.8 ± 0.0 mm fazla su
   (israf). Hata düzeltilmediği için sezon boyunca büyüyor.
3. **EnKF iki hatayı da büyük ölçüde düzeltiyor, ama yanlılık yönü önemli.** b = 1'de kestirim RMSE
   1.91 ± 0.22 mm (sensörün ~1/5'i). f = 0,8 ile fazla su 16.8 ± 3.1 mm ve
   0.7 ± 1.0 stres günü/yıl, yani kâhine yakın ve neredeyse stressiz.
   b = 1,1'de (ikiz kuruluğu fazla görüyor) stres kalkıyor (0.3 ± 0.6 gün, f = 0,9),
   bedeli fazladan su (17.7 ± 2.9 mm). b = 0,9'da (ikiz kuruluğu az görüyor) EnKF
   yanlılığı yalnız kısmen düzeltiyor (kestirim yanlılığı -2.77 ± 0.38 mm):
   f = 0,9'da 84.2 ± 8.4 stres günü, f = 0,8'de 28.1 ± 8.2. **ETo'yu
   olduğundan düşük gören bir ikiz, stresi sistematik olarak artırır**; güvenlik payı bu yanlılığa
   göre seçilmeli.
4. **Mevcut S4 ile kıyas (b = 1):** S4 kâhinden 29.6 ± 8.9 mm fazla su ve
   17.0 ± 3.7 stres günü/yıl üretiyor. S5-EnKF f = 0,8: 16.8 ± 3.1 mm ve
   0.7 ± 1.0 stres günü. Aynı sensör ve aynı EnKF sınıfıyla, JIT doz kuralı ve doğru
   zamanlama hem suyu hem stresi azaltıyor. S4, 35 mm üst sınırından da etkileniyor (§10.3).
5. **Tez için çıkarım (RQ1 / H1):** EnKF her b için yalnız sensörden daha küçük kestirim hatası ve
   daha iyi karar veriyor. Yalnız modelden (açık döngü) daha iyi olması ise **yalnız model hatası
   varken (b ≠ 1)** geçerli. b = 1'de açık döngü kusursuz, çünkü bu kurulumda ikizin modeli
   "gerçek"le aynı. H1'in bu kurulumdaki desteği bu koşula bağlı; gerçek sensörle doğrulanmadı.

### 12.4 Bulgu: S4AssimilatedTwin zamanlaması tutarsız (düzeltilmedi, Burak'ın onayını bekliyor)

`src/twin/sim/strategies.py`, `S4AssimilatedTwin.decide`:
- `forecast_step` **bugünün** `weather_row` değerleriyle (ETo, yağış) çalışıyor. Sabah karar anında
  bugünün gerçekleşmiş ETo'su ve yağışı bilinmez; bu bir ileriye bakmadır (look-ahead).
- Ardından `analysis_step`, motorun ürettiği ve **Dr_(t−1)'i** (önceki gün sonu) ölçen gözlemle
  yapılıyor. Yani bugünün sonuna ilerletilmiş tahmin, dünün sonunu ölçen gözlemle güncelleniyor.
- `forecast_step`'e verilen sulama `last_irr_gross_mm` dünkü dozdur, ama bugünün havasıyla birleştiriliyor.

Bu, CLAUDE.md §5 "Doğrulanacak 3"ün yanıtıdır: S4 bir tahmin adımı içeriyor, ama zamanlaması tutarsız.
S4'ün mevcut sonuçları (§6, §10, §11) bu kusuru içerir. **Önerilen düzeltme:** `EstimatedPersistenceJIT`
("enkf") gibi önce dünkü hava ve dünkü dozla `forecast_step`, sonra bugünkü gözlemle `analysis_step`.
Doz kuralı (doldur ya da JIT) ayrı bir karar. Bu oturumda `strategies.py`'ye dokunulmadı.

### 12.5 Doğrulanmayanlar ve sınırlılıklar

- "Gerçek" su dengesi ile ikizin modeli, b dışında aynı. Süreç gürültüsü, toprak parametresi
  uyumsuzluğu ve alan içi heterojenlik yok; açık döngünün b = 1 sonucu bu yüzden iyimser.
- Sensör gürültüsü yansız, bağımsız ve Gauss. Kayma, donma, sıçrama ve boşluk (arıza enjeksiyonu)
  bu deneyde yok. Sensör yalnız kök bölgesinin ortalama θ'sını ölçüyor varsayıldı.
- EnKF'nin zorlama pertürbasyonları (ETo %15, yağış %20) `model/assimilation.py` içinde sabit; config'te
  `ParameterItem` değil (CLAUDE.md kural 5'e aykırı). Süreç gürültüsü σ = 0,8 mm config'ten geliyor ama
  `assumption`. EnKF forecast_step yüzey akışı eşiğini parametre olarak almıyor; varsayılan 25 mm
  config ile aynı.
- b senaryosu ETo'yu her gün aynı oranda kaydırıyor; gerçek ERA5 yanlılığı mevsime ve güne göre değişebilir.
- 10 tohum, 5 yıl. S2 ve "true"/"openloop" kestiricileri tohumdan bağımsız (std = 0).
