# Hava tahmini isabeti ve tahmine dayalı kararın değeri

Durum: 2026-11-20. Kod: `src/twin/data/forecast.py`, `src/twin/sim/forecast_skill.py`; testler
`tests/test_forecast_skill.py`; komut `twin forecast-skill --year 2024 --seeds 10` (karar koşusu 28,3 s).
Çıktılar: `outputs/forecast_skill/skill_yildiz_2024.csv`, `decision_value_yildiz_2024.csv`.
Tahmin arşivi: `data/external/open_meteo_previous_runs_yildiz_2024.csv`.

## 1. Veri

- **Tahmin:** Open-Meteo Previous Runs API (`previous-runs-api.open-meteo.com`). Saatlik `et0_fao_evapotranspiration`
  ve `precipitation`, k = 0–7 gün önce yapılmış koşulardan; UTC günlerine toplandı. Model ızgara noktası
  41,030 K; 29,018 D (parkın yaklaşık 2 km güneyi). Bu arşiv 2024'ten önce boş döndü (2021-07-01, 2022-07-01 ve
  2023-07-01 denendi); vade bazlı isabet yalnız **2024 sezonu** (1 Nisan–31 Ekim, 214 gün) için ölçülebildi.
- **Referans:** ERA5-Land günlük değerleri (`data/processed/era5_yildiz_2024.csv`, kaynak `era5`). ERA5 bir
  reanalizdir, istasyon ölçümü değildir; ETo'su bu projede FAO-56 PM ile hesaplandı. Open-Meteo ETo'su kendi
  modelinin FAO-56 hesabıdır. Fark yöntem, ızgara (ERA5 hücresi 41,0 K; 29,0 D) ve model farkını birlikte içerir.
- **Taban:** kalıcılık, yani bugünkü değer = dünkü ERA5 değeri.

## 2. ETo isabeti (2024, mm/gün)

| tahmin | gün | yanlılık (mm/gün) | MAE | RMSE | r | toplam tahmin (mm) | toplam ERA5 (mm) |
|---|---|---|---|---|---|---|---|
| 1 gün önce | 214 | -0.075 | 0.414 | 0.512 | 0.947 | 861.75 | 877.897 |
| 2 gün önce | 214 | -0.056 | 0.45 | 0.571 | 0.933 | 865.81 | 877.897 |
| 3 gün önce | 214 | -0.0 | 0.509 | 0.662 | 0.908 | 877.89 | 877.897 |
| 4 gün önce | 214 | -0.088 | 0.584 | 0.742 | 0.883 | 859.05 | 877.897 |
| 5 gün önce | 214 | 0.058 | 0.57 | 0.761 | 0.877 | 890.36 | 877.897 |
| 6 gün önce | 214 | 0.124 | 0.574 | 0.774 | 0.875 | 904.39 | 877.897 |
| 7 gün önce | 214 | 1.047 | 1.137 | 1.318 | 0.891 | 1101.9 | 877.897 |
| kalıcılık (dün) | 213 | 0.006 | 0.521 | 0.689 | 0.904 | 875.87 | 874.631 |

## 3. Yağış isabeti (2024)

POD = yakalanan yağışlı gün oranı, FAR = yanlış alarm oranı, CSI = kritik başarı indeksi. ERA5'te ≥ 1 mm yağışlı
gün sayısı 45, ≥ 5 mm 13.

| tahmin | yanlılık | MAE | r | toplam tahmin | toplam ERA5 | POD ≥1 | FAR ≥1 | CSI ≥1 | POD ≥5 | FAR ≥5 | CSI ≥5 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 gün önce | -0.423 | 0.776 | 0.824 | 149.0 | 239.419 | 0.422 | 0.05 | 0.413 | 0.385 | 0.5 | 0.278 |
| 2 gün önce | -0.4 | 0.725 | 0.845 | 153.9 | 239.419 | 0.4 | 0.1 | 0.383 | 0.538 | 0.125 | 0.5 |
| 3 gün önce | -0.504 | 0.979 | 0.583 | 131.6 | 239.419 | 0.333 | 0.25 | 0.3 | 0.308 | 0.6 | 0.211 |
| 4 gün önce | -0.546 | 0.955 | 0.525 | 122.6 | 239.419 | 0.511 | 0.258 | 0.434 | 0.231 | 0.571 | 0.176 |
| 5 gün önce | 0.038 | 1.602 | 0.385 | 247.5 | 239.419 | 0.289 | 0.409 | 0.241 | 0.154 | 0.833 | 0.087 |
| 6 gün önce | -0.333 | 1.594 | 0.051 | 168.1 | 239.419 | 0.289 | 0.409 | 0.241 | 0.077 | 0.9 | 0.045 |
| 7 gün önce | -0.908 | 1.081 | 0.248 | 45.2 | 239.419 | 0.2 | 0.4 | 0.176 | 0.0 | 1.0 | 0.0 |
| kalıcılık (dün) | -0.0 | 1.538 | 0.145 | 239.415 | 239.418 | 0.556 | 0.444 | 0.385 | 0.077 | 0.923 | 0.04 |

## 4. Tahmine dayalı kararın değeri (sanal park, 2024, 10 sensör tohumu)

Dünya her durumda ERA5 havasıyla yürür (`yildiz_dunya.json`, dünya tohumu 7). İkiz kararı üç bilgi düzeyinde
verilir: **kalıcılık** (dünkü ETo, yağış 0), **tahmin** (1 gün önce yayımlanmış Open-Meteo ETo ve yağışı),
**kusursuz tahmin** (o günün ERA5 değerleri, üst sınır). Güvenlik payı 0,9. Sonuç `synthetic_world` etiketlidir.

| ikiz | bilgi | su (m³, ort. ± sd) | kalıcılığa göre su % | strese giren alan % (ort. ± sd) | derin sızma (m³) |
|---|---|---|---|---|---|
| ENKF | kalıcılık | 154,530 ± 533 | 0.0 | 25.9 ± 0.3 | 6,561 |
| ENKF | tahmin (1 gün önce) | 152,915 ± 545 | -1.04 | 26.9 ± 0.3 | 5,705 |
| ENKF | kusursuz tahmin | 152,727 ± 543 | -1.17 | 27.8 ± 0.3 | 5,616 |
| MODEL | kalıcılık | 169,149 ± 0 | 0.0 | 18.7 ± 0.0 | 8,110 |
| MODEL | tahmin (1 gün önce) | 167,697 ± 0 | -0.86 | 19.8 ± 0.0 | 7,291 |
| MODEL | kusursuz tahmin | 167,441 ± 0 | -1.01 | 21.1 ± 0.0 | 7,155 |
| SENSOR | kalıcılık | 168,376 ± 4,658 | 0.0 | 16.8 ± 0.5 | 14,431 |
| SENSOR | tahmin (1 gün önce) | 166,462 ± 4,617 | -1.14 | 17.1 ± 0.5 | 13,169 |
| SENSOR | kusursuz tahmin | 165,812 ± 4,566 | -1.52 | 17.4 ± 0.6 | 12,826 |

## 5. Bulgular

1. **ETo:** 1 ve 2 gün önceki tahmin kalıcılıktan iyi (MAE 0,414 ve 0,450; kalıcılık 0,521 mm/gün). 3 günden
   itibaren üstünlük kayboluyor. 7 gün önceki koşuda sezon boyunca +1,047 mm/gün yanlılık var (toplam 1.101,9 mm,
   ERA5 877,9 mm). Bunun nedeni incelenmedi; bu vade kararda kullanılmamalı.
2. **Yağış:** 1 gün önceki tahmin ERA5'teki ≥ 1 mm yağışlı günlerin %42,2'sini yakalıyor, yanlış alarmı %5,0.
   Sezon toplamını eksik veriyor (149,0 mm; ERA5 239,4 mm). ERA5'in hafif yağışı fazla gösterme eğilimi bu farkın
   bir kısmı olabilir (bellekten, **doğrulanmadı**); istasyon verisiyle kontrol edilmeli.
3. **Kararın değeri küçük:** gerçek tahmin, kalıcılığa göre suyu ikizlere göre %-1.14 ile %-0.86
   arasında değiştiriyor (eksi = daha az su); kusursuz tahmin bile %-1.52 ile %-1.01 arasında. Buna karşılık strese giren alan
   biraz artıyor: tahmin, yağış beklenen günlerde dozu düşürüyor ve kalıcılığın verdiği fazladan tamponu kaldırıyor.
4. Bu sanal parkta strese giren alanın asıl nedeni tahmin değil, zon içi heterojenlik (zon ortalamasıyla
   sulamak). Tahmin, bu kurguda ve bu tek sezonda verimliliğin belirleyicisi değil. **Negatif sonuç olarak raporlanmalı.**

## 6. Sınırlılıklar

- Tek sezon (2024), tek konum; Open-Meteo karışık model ("best match") koşularıdır, model bileşimi zamanla değişmiş olabilir.
- Yağış olasılığı arşivde yok; karar deterministik tahmin miktarıyla verildi (canlı ekranda miktar × olasılık).
- Karar kuralı 1 günlük tam zamanında (JIT) sulamadır; çok günlük erteleme (ör. 2–3 gün sonraki yağışı bekleme)
  denenmedi. Tahminin değeri çok günlük kurallarda farklı çıkabilir.
- Referans ERA5'tir; istasyon (MGM/İBB) verisiyle doğrulanmadı.
