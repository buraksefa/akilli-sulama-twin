# Kütüphane Modülleri ve Bilimsel Formül Tablosu

Bu belge, `src/twin/` kütüphanesinin modül yapısını, uygulanan bilimsel yöntemleri, denklem numaralarını ve birimlerini belgeler.

## 1. Modül Mimarisi

```
src/twin/
├── config.py           # Parametre kayıt sistemi (verified / to_verify / assumption)
├── data/
│   ├── era5.py         # ERA5-Land NetCDF yükleme, deaccumulation ve birim dönüşümleri
│   ├── parks.py        # Park poligonları ve sulama bölgeleri (zones)
│   └── sentinel2.py    # Sentinel-2 SCL bulut filtreli NDVI serisi
├── model/
│   ├── et0.py          # FAO-56 Penman-Monteith (günlük/saatlik) ve Hargreaves ETo
│   ├── kc.py           # Aşama bazlı (tablo) ve NDVI bazlı Kc
│   ├── waterbalance.py # FAO-56 Bölüm 8 Kök Bölgesi Toprak Su Dengesi (TAW, RAW, Ks, ETa, DP)
│   └── assimilation.py # Veri asimilasyonu: Nudging ve Topluluk Kalman Filtresi (EnKF)
├── qc/
│   ├── rules.py        # SIMPaCT kural filtreleri (boşluk, donma, sıçrama, fiziksel aralık)
│   ├── isolation_forest.py # 200 ağaçlı mevsimsel fark Isolation Forest anomali filtresi
│   ├── arima_check.py  # 24 saatlik ARIMA kalıntı testi (|gerçek - tahmin| > 2σ)
│   └── virtual_sensor.py # KSG Karşılıklı Bilgi + MLP ve ERA5 fiziksel su dengesi yedeği
├── forecast/
│   ├── knn.py          # Kayan pencereli kNN 24-72 saat toprak nemi yörünge tahmincisi
│   └── sarima.py       # Mevsimsel ARIMA referans tahmincisi
├── sim/
│   ├── strategies.py   # S0 (Takvim), S1 (Sensör), S2 (ET), S3 (Tahminli), S4 (İkiz)
│   ├── engine.py       # Sezonluk kurgu (2015-2025) ve strateji koşturucu
│   ├── metrics.py      # Su (mm, m³), stres günleri, RMSE, Bias, KGE, NSE
│   ├── critic.py       # CRITIC objektif çok kriterli ağırlıklandırma ve sıralama
│   ├── sensitivity.py  # OAT ve Sobol parametre duyarlılık analizleri
│   ├── fault_injection.py # RQ1 sensör arıza enjeksiyon modelleri
│   └── plots.py        # Tez kalitesinde Matplotlib grafik üretimi
├── api/                # FastAPI REST API servisi ve OpenAPI şeması
├── ui/                 # Streamlit 'Senaryo Gezgini' etkileşimli arayüzü
└── cli.py              # Typer CLI komut satırı arayüzü
```

---

## 2. Bilimsel Formül ve Kaynak Tablosu

| Modül | Formül / Yöntem | Kaynak / Standart | Doğrulama Durumu | Birim |
| --- | --- | --- | --- | --- |
| `model/et0.py` | Standart Atmosfer Basıncı: $P = 101.3 \left(\frac{293 - 0.0065 z}{293}\right)^{5.26}$ | FAO-56 Denklem 7 | Verified | $\text{kPa}$ |
| `model/et0.py` | Psikrometrik Sabit: $\gamma = 0.000665 P$ | FAO-56 Denklem 8 | Verified | $\text{kPa}/^\circ\text{C}$ |
| `model/et0.py` | Doymuş Buhar Basıncı: $e^\circ(T) = 0.6108 \exp\left(\frac{17.27 T}{T + 237.3}\right)$ | FAO-56 Denklem 11 | Verified | $\text{kPa}$ |
| `model/et0.py` | Buhar Basıncı Eğimi: $\Delta = \frac{4098 e^\circ(T)}{(T + 237.3)^2}$ | FAO-56 Denklem 13 | Verified | $\text{kPa}/^\circ\text{C}$ |
| `model/et0.py` | Atmosfer Dışı Radyasyon ($R_a$) & Açık Gökyüzü ($R_{so}$) | FAO-56 Denklemler 21-25, 37 | Verified | $\text{MJ}/(\text{m}^2\cdot\text{gün})$ |
| `model/et0.py` | FAO-56 Günlük Penman-Monteith $ET_0$ | FAO-56 Denklem 6 | Verified (Örnek değerler testli) | $\text{mm}/\text{gün}$ |
| `model/et0.py` | FAO-56 Saatlik Penman-Monteith $ET_0$ | FAO-56 Denklem 53 | Verified | $\text{mm}/\text{saat}$ |
| `model/et0.py` | Hargreaves-Samani $ET_0 = 0.0023(T_{mean}+17.8)(T_{max}-T_{min})^{0.5} R_a \cdot 0.408$ | FAO-56 Denklem 52 | Verified | $\text{mm}/\text{gün}$ |
| `data/era5.py` | 10m $\to$ 2m Rüzgâr Dönüşümü: $u_2 = u_{10} \frac{4.87}{\ln(67.8(10) - 5.42)}$ | FAO-56 Denklem 47 | Verified | $\text{m}/\text{s}$ |
| `model/kc.py` | Aşama Bazlı $K_c$ (Çim/Park) | FAO-56 Tablo 12 & WUCOLS | To Verify | $-$ |
| `model/kc.py` | NDVI Bazlı $K_c = NDVI^2$ | Obriejetan & Krexner (2024), Viyana | Assumption (Kalibre edilecek) | $-$ |
| `model/waterbalance.py` | Toplam Kullanılabilir Su: $TAW = 1000(\theta_{FC} - \theta_{WP}) Z_r$ | FAO-56 Denklem 82 | Verified | $\text{mm}$ |
| `model/waterbalance.py` | Kolay Kullanılabilir Su: $RAW = p \cdot TAW$ | FAO-56 Denklem 83 | Verified | $\text{mm}$ |
| `model/waterbalance.py` | Su Stres Katsayısı: $K_s = \frac{TAW - D_r}{(1-p)TAW}$ ($D_r > RAW$) | FAO-56 Denklem 84 | Verified | $-$ |
| `model/waterbalance.py` | Gerçek Evapotranspirasyon: $ET_a = K_s K_c ET_0$ | FAO-56 Denklem 81 | Verified | $\text{mm}/\text{gün}$ |
| `model/waterbalance.py` | Kök Tükenme Güncellemesi: $D_{r,i} = D_{r,i-1} - (P-RO) - I_{eff} + ET_a + DP$ | FAO-56 Denklem 85 | Verified (Kütle korunumu testli) | $\text{mm}$ |
| `model/assimilation.py` | Gözlem Operatörü: $\theta = \theta_{FC} - \frac{D_r}{1000 Z_r}$ | Nasirahmadi & Hensel (2022) | Verified | $\text{m}^3/\text{m}^3$ |
| `model/assimilation.py` | Sensör Hata Modeli: $\theta_{obs} = a \cdot \theta_{true} + b + \epsilon$ | Tezin RQ1 Arıza Modeli | Assumption / Testbed | $\text{m}^3/\text{m}^3$ |
| `qc/isolation_forest.py` | Isolation Forest (200 ağaç, contamination=0.05, >%30 pencere eşiği) | Koçyiğit vd. (2025) SIMPaCT | Verified | $-$ |
| `qc/arima_check.py` | 24 Adımlık ARIMA Kalıntı Testi ($|e| > 2\sigma$, >%30 aşım eşiği) | Koçyiğit vd. (2025) SIMPaCT | Verified | $-$ |
| `qc/virtual_sensor.py` | KSG Karşılıklı Bilgi + 1 Gizli Katman 10 ReLU MLP Sanal Sensör | Kraskov vd. (2004), Koçyiğit vd. (2025) | Verified | $\text{m}^3/\text{m}^3$ |
| `sim/critic.py` | CRITIC Objektif Ağırlıklandırma: $C_j = \sigma_j \sum (1 - r_{jk})$ | Diakoulaki vd. (1995) | Verified | $-$ |
| `sim/metrics.py` | Nash-Sutcliffe Verimliliği (NSE) & Kling-Gupta (KGE) | Nash & Sutcliffe (1970), Gupta vd. (2009) | Verified | $-$ |
