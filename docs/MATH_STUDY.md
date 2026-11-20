# Su kullanım verimliliği: matematiksel model çalışması

Durum (13 Kasım 2026): formülasyon ve analitik sonuçlar hazır, `math_checks.py` ile sayısal olarak doğrulandı.
Sayısal deneyler (Bölüm 5) **henüz koşulmadı**; gerçek ERA5 sunucuda olduğu için lokalde koşulacak.
Bu dosyadaki sayılar yalnızca Bölüm 1'deki **varsayım** parametreleriyle ve sabit ETc ile elde edilmiştir;
tezde "ölçüm" ya da "gerçek veri sonucu" diye sunulamaz.

## 1. Model ve varsayımlar

Günlük adım `t = 1..T` (Nisan–Ekim, T = 214). Durum: kök bölgesi tükenmesi `Dr` [mm], `0 ≤ Dr ≤ TAW`.
Sulama günün başında uygulanır, sonra ETa oluşur.

```
TAW = 1000 (θFC − θWP) Zr            RAW = p · TAW
Ks  = 1                              Dr ≤ RAW
Ks  = (TAW − Dr) / (TAW − RAW)       Dr > RAW          (FAO-56 denklem 84; numara kaynaktan teyit edilecek)
ETc = Kc · ETo                       ETa = Ks · ETc
Dr_t = Dr_{t-1} − (P_t − RO_t) − η I_t + ETa_t + DP_t     (DP_t ≥ 0: tarla kapasitesini aşan fazla)
```

`I` brüt sulama [mm], `η` uygulama verimi, `P` yağış, `RO` yüzey akışı, `DP` derin sızma.

| Parametre | Kontrol değeri | Durum |
| --- | --- | --- |
| θFC / θWP | 0,32 / 0,15 | varsayım (toprak dokusu bilinmiyor) |
| Zr | 0,30 m | varsayım |
| p | 0,50 | varsayım (FAO-56 çim için aralık; kaynaktan teyit) |
| η | 0,75 | varsayım (yağmurlama için tipik; İBB kap testiyle ölçülecek) |
| TAW / RAW | 51 / 25,5 mm | türetilmiş |

Gerçek koşularda değerler `src/twin/config.py` içindeki `ParameterItem`'lardan okunur; bu tablo yalnızca kontrol içindir.

## 2. Verimlilik ölçütleri

Tek bir "verimlilik" sayısı yetmez; su ve stres birlikte raporlanır. Yalnız suya bakmak yanıltır (Bölüm 4, A2b).

- **Su:** `W = Σ I` [mm]; hacim `V = A_sulanan · W / 1000` [m³].
- **Stres:** `S = 1 − ΣETa / ΣETc` (bağıl ETa kaybı), stres günü sayısı `#{Ks < 1}`.
- **Kayıp:** `ΣDP` (sulama ve yağmurla gelen fazla su).
- **Marjinal sulama verimi:** `IE = (ΣETa(I) − ΣETa(I = 0)) / W` ≤ η. Sulamasız karşı-olgusal koşuyla hesaplanır.
- **Operasyonel maliyet:** sulama olayı sayısı `N`.
- **Tasarruf:** `1 − W / W_ref`, yalnızca eşit stres düzeyinde (`S` farkı ≤ ε) karşılaştırılırsa anlamlıdır.

## 3. Bilgi düzeyleri ve stratejiler

Stratejiler farklı bilgiyle karar verir. Karşılaştırma bilgi ile verimlilik arasındaki ilişkiyi ölçer.

| Düzey | Strateji | Bilgi |
| --- | --- | --- |
| I0 | S0 sabit takvim | yok |
| I1 | S1 sensör eşiği | gürültülü, yanlı sensör |
| I2 | S2 yalnız ET | ERA5 sürücüleri ile açık çevrim model (sürücü hatalı) |
| I3 | S3 tahminli | I2 + yağış tahmini (beceri `κ`) |
| I4 | S4 asimile ikiz | I3 + sensörle Kalman/EnKF düzeltmesi |
| I∞ | Kâhin (DP) | gerçek hava ve gerçek durum; **alt sınır** |

Kâhin: gerçekleşen hava dizisi için `min_I Σ I + λ · Σ(ETc − ETa)` problemini dinamik programlamayla çözer
(durum ızgarası 0,5 mm, eylem 0–35 mm). `λ` taranarak su–stres Pareto sınırı çıkar. Hiçbir strateji bu sınırın
altına inemez; "optimallik farkı" tezin ana nicel çıktısıdır.

## 4. Analitik sonuçlar (math_checks.py ile doğrulandı)

### A1. Kütle dengesi ve alt sınır
`Dr_baş = 0` ile `η W = ΣETa + ΣDP − Dr_son`. Yağışsız ve stressiz durumda `W ≥ (ΣETc − Dr_son) / η`; eşitlik
`ΣDP = 0` iken geçerlidir. Yağışlı durumda alt sınır `(ΣETc − ΣP_etkin − ΔS) / η`; `P_etkin` zamanlamaya
(depoda boşluk olmasına) bağlı olduğu için sayısal kâhin gerekir.
Kontrol: sabit ETc = 5 mm/gün, eşik stratejisi, yanlılıksız → `W = 1400,0 mm = (ΣETc − Dr_son)/η`, DP = 0, stres günü 0.

### A2a. Sensör "kuru okuyorsa" (`b < 0`) fazla su harcanır
`θ_obs = θ_gerçek + b`. Tükenme karşılığı `δ = 1000 · Zr · b` [mm]. Tahmini tükenme `Dr_tah = Dr − δ`.
Eşik `Dr_tah ≥ RAW` olduğu için sulama gerçek tükenme `RAW − |δ|` iken başlar ve her olayda `|δ|` mm net fazla uygulanır (DP).

```
N ≈ ΣETc / (RAW − |δ|)        ΔW ≈ N · |δ| / η        ΔW / W0 ≈ |δ| / (RAW − |δ|)
```

Ayrık adım nedeniyle yaklaşım ±%12 içinde kalır.

| b (hacim) | δ [mm] | ΔW (simülasyon) | ΔW (formül) | ΔW / W0 |
| --- | --- | --- | --- | --- |
| −0,01 | 3 | +168 mm | +190 mm | %12 |
| −0,02 | 6 | +437 mm | +439 mm | %31 |
| −0,04 | 12 | +1156 mm | +1268 mm | %83 |

**Tasarım sonucu:** fazla su ≤ x ise `|b| ≤ x · RAW / ((1 + x) · 1000 · Zr)`. Kontrol değerleriyle x = %5 için
`|b| ≤ 0,0040` (yaklaşık **%0,4 hacim**). Ucuz kapasitif sensörlerin fabrika doğruluğu bundan çok kötüdür
(literatür değeri doğrulanacak). Yani ham sensör değerine eşik koymak yetmez; yerinde kalibrasyon, görece
(eşik-kalibrasyonlu) kullanım ya da model ile asimilasyon gerekir. Bu, RQ1 için analitik temeldir.

### A2b. Sensör "ıslak okuyorsa" (`b > 0`) su azalır ama bu tasarruf değildir
Sulama gerçek tükenme `RAW + δ` iken başlar, bitki stres yaşar.

| b (hacim) | W | ΔW | Stres günü | ΣETa / ΣETc |
| --- | --- | --- | --- | --- |
| +0,01 | 1373,8 mm | −%1,9 | 34 | 0,984 |
| +0,02 | 1345,0 mm | −%3,9 | 69 | 0,962 |
| +0,04 | 1240,2 mm | −%11,4 | 105 | 0,885 |

Su düşüşü stres bedeliyle gelir; bu yüzden tasarruf yalnızca eşit stres düzeyinde raporlanır (Bölüm 2).

### A3. Kalman kararlı hal varyansı (skaler)
Durum `Dr` rasgele yürüyüş (süreç gürültüsü `q` [mm²/gün], sürücü hatasından), gözlem varyansı `r` [mm²]
(`r = (1000 Zr σ_s)²`). Kararlı halde:

```
P⁻ = (q + sqrt(q² + 4 q r)) / 2        K = P⁻ / (P⁻ + r)        P⁺ = (1 − K) P⁻ < min(r, P⁻)
```

Kontrol (sayısal iterasyonla eşleşti). Örnek: ETo hatası %15 → `q = (0,15 · 5)² = 0,5625`; sensör `σ_s = 0,02` →
`r = 36`. Sonuç: `P⁻ = 4,79` (σ = 2,19 mm), `K = 0,117`, `P⁺` σ = 2,06 mm; sensör tek başına σ = 6 mm; açık çevrim
modelin σ'sı 10 günde 2,37 mm, 30 günde 4,11 mm.

**Dürüst okuma:** bu varsayımlarda kazanç düşük (`K = 0,12`). Rasgele yürüyüş modeli kısa vadede sensörden iyidir;
asimilasyonun asıl değeri **sistematik** sürücü hatasında (ETo yanlılığı, Kc hatası, kaçırılan yağış) çıkar. H1'i sınamak
için durum vektörüne yanlılık terimi eklenmelidir (`x = [Dr, β]`, `ETc_gerçek = (1 + β) ETc_model`).
H1 bu yüzden "sürücü yanlılığı varken" biçiminde yazılmalıdır; bu bir beklenti, sonuç değil.

## 5. Sayısal deney tasarımı (lokalde koşulacak, gerçek ERA5 ile)

Ortak: 2020–2024 sezonları (gerçek), ayrıca ERA5'ten uydurulan hava üretecinden çoklu gerçekleşme (etiket: `synthetic_from_era5`).
Doğruluk (truth) ve model sürücüleri **ayrı** olmalı: `ETo_model = ETo_gerçek (1 + β + ε_t)`, `P_model = P_gerçek · LN(0, σ_P)`.

| Deney | Çıktı | Soru |
| --- | --- | --- |
| E1 Kâhin DP + `λ` taraması | Pareto sınırı (W, S) | alt sınır nerede |
| E2 S0–S4 + eşik `α` taraması | strateji eğrileri | her bilgi düzeyi sınıra ne kadar yakın (H3) |
| E3 Sensör hata simülasyonu | W, S vs (b, σ_s, kayma, donma) | A2'nin doğrulanması; RQ1 |
| E4 Asimilasyon (yanlılık durumlu) | durum RMSE, W, S | H1, H2 |
| E5 Sobol (SALib) | S1, ST: θFC, θWP, Zr, p, η, Kc ölçeği, ETo yanlılığı, `σ_P`, `σ_s`, `κ` | RQ3; İBB veri talebi önceliği |
| E6 Güç analizi | `n = 2 (z_{α/2} + z_β)² σ_d² / d²` | kaç sezon/gerçekleşme gerekli |

Tutarlılık için ortak rastgele sayılar kullan; her sonuç kaynak etiketli (`era5_land` / `synthetic` / `synthetic_from_era5`).

## 6. Tasarım gereksinimlerine çıkarım

| Konu | Kural | Not |
| --- | --- | --- |
| Sensör yanlılığı | `|b| ≤ x · RAW / ((1 + x) · 1000 · Zr)` | x = %5 için ≈ %0,4 hacim (A2a) |
| Düğüm sayısı / bölge | `n = (z · CV / E)²` | `CV` mekânsal değişkenlik testbed'de ölçülecek; varsayım yok |
| Örnekleme | günlük karar, saatlik örnekleme, günlük medyan | QC sıçrama kuralıyla uyumlu (24 saat kayan medyan) |
| Kalibrasyon | yerinde gravimetrik referans | ölçüm sırası testbed planında |
| Veri talebi öncelikleri | E5 sıralamasına göre | dilekçe Ek-1 listesiyle eşleştir |

## 7. Park ölçeğine ölçekleme

`V_p = A_p · f_p · W / 1000` [m³], `f_p` sulanan oran (bilinmiyor; İBB cevabına kadar senaryo parametresi, ör. 0,1–0,5).
Poligon alanları: Yıldız Korusu 389.760 m², Maçka Demokrasi Parkı 139.419 m² (`parks.csv`; Beşiktaş yeşil alan
dosyasındaki aynı poligonlarla tutuyor). Aynı dosyada Beşiktaş için 32 poligon, toplam 1.158.349 m² (Park: 12 poligon
280.774 m²; Karayolu/refüj ve cadde tipleri ayrı) bulunuyor. İBB yıllık yeşil alan suyu (2017–2025, 13,4–18,8 milyon m³)
**kapsamı belirsiz**; park bazlı değil. Yalnızca büyüklük sırası için kullanılabilir ve bunun için İBB'den kapsam
bilgisi dilekçede istendi.

## 8. Mevcut kodda doğrulanacak noktalar (eski kopyadan okundu; güncel kodda teyit et)

1. `sim/engine.py::prepare_season_weather` `generate_synthetic_era5` çağırıyor; gerçek ERA5 bağlı değil.
2. S2, S3, S4 `state_depletion_mm` (gerçek durum) kullanıyor; açık çevrim model ve model hatası yok, S2 "sensörsüz" değil.
3. S4: `enkf.analysis_step(sensor_theta_obs)` yalnız gözlemle çağrılıyor; ETo/yağış/sulamayla tahmin adımı görünmüyor.
4. Yağış tahmini = ertesi gün gerçek yağış + N(0, 1 mm); kâhin, yanlış alarm/kaçırma yok.
5. Tek rastgele tohum (42) ve sabit sensör gürültüsü; belirsizlik bandı yok.
6. `api/app.py` varsayılan token (`"gsutwin2026"`) içeriyorsa kaldır, yoksa teyit et.

## 9. Lokalde ilk işler (sırayla)

1. `python math_checks.py` çalıştır; çıktı Bölüm 4 ile aynı olmalı.
2. Bölüm 8, madde 1–3'ü düzelt (gerçek ERA5, ayrı truth/model, EnKF tahmin adımı); testlerini yaz.
3. E1, E2, E3'ü gerçek ERA5 ile koştur; `outputs/` altına kaynak etiketli yaz, bana ham tabloları göster.
4. E4, E5, E6; sonra sonuçları tez yöntem bölümüne çevir.

## 10. Kaynak durumu

FAO-56 (Allen vd., 1998), CRITIC (Diakoulaki vd., 1995), Kalman/EnKF literatürü: bellekten; denklem numaraları ve
literatürdeki sensör doğruluğu değerleri kaynaktan doğrulanacak. SIMPaCT eşikleri `docs/THESIS_FRAME.md` içinde
tam metinden doğrulanmış olarak işaretli.
