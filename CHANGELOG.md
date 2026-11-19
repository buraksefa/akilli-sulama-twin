# Değişiklik Günlüğü (CHANGELOG)

## [0.1.0] - 2026-10-14

### Eklenenler (Faz 1 - Çekirdek Kütüphane)
- `pyproject.toml` ve `src/twin/` paket mimarisi kuruldu.
- `src/twin/config.py`: Tüm fiziksel parametreler için kaynak (`source`) ve doğrulama durumu (`status: verified | to_verify | assumption`) kayıt yapısı.
- `src/twin/data/era5.py`: ERA5-Land NetCDF yükleyici, 00 UTC birikimli değişken açma (deaccumulation), Kelvin $\to$ °C, J/m² $\to$ W/m² ve m $\to$ mm dönüşümleri.
- `src/twin/data/parks.py`: `data/public/parks.geojson` yükleyici, park alanı, centroid ve varsayılan sulama bölgeleri (zones) modellemesi.
- `src/twin/data/sentinel2.py`: Sentinel-2 SCL bulut maskeli NDVI serisi ve çevrimdışı sentetik sağlayıcı.
- `src/twin/model/et0.py`: FAO-56 Penman-Monteith (günlük/saatlik) ve Hargreaves referans evapotranspirasyon formülleri.
- `src/twin/model/kc.py`: Aşama bazlı tablo ve $K_c = \text{NDVI}^2$ dinamik bitki katsayısı modelleri.
- `src/twin/model/waterbalance.py`: FAO-56 Bölüm 8 kök bölgesi su dengesi (TAW, RAW, Ks, ETa, DP, RO) ve su dengesi kütle korunumu doğrulama testi.
- `src/twin/model/assimilation.py`: Sensör hata modeli, Direct Nudging ve Topluluk Kalman Filtresi (EnKF) durum asimilasyonu.
- `src/twin/qc/`: SIMPaCT kural filtreleri (boşluk, sıçrama, donma, fiziksel aralık), Isolation Forest (200 ağaç), 24 saatlik ARIMA kalıntı testi ($2\sigma$) ve KSG+MLP / ERA5 sanal sensör yedeği.
- `src/twin/forecast/`: Kayan pencereli kNN ve SARIMA toprak nemi yörünge tahmincileri.

### Eklenenler (Faz 2 - Simülasyon ve Değerlendirme)
- `src/twin/sim/strategies.py`: 5 sulama stratejisi (S0 Sabit Takvim, S1 Sensör Eşiği, S2 Yalnız ET, S3 Tahminli, S4 Asimile İkiz).
- `src/twin/sim/engine.py`: 2015-2025 sezonluk simülasyon kurgusu ve çoklu strateji koşturucu.
- `src/twin/sim/metrics.py`: Su tüketimi (mm, m³), bitki stres günleri ($K_s < 1.0$), RMSE, Yanlılık, KGE, NSE metrikleri.
- `src/twin/sim/critic.py`: CRITIC objektif çok kriterli karar verme ve strateji sıralaması.
- `src/twin/sim/sensitivity.py`: OAT ve Sobol parametre duyarlılık analizleri ($K_c, Z_r, \theta_{FC}, \theta_{WP}, p$).
- `src/twin/sim/fault_injection.py`: RQ1 sensör yanlılık, kayma, donma ve kopma arıza enjeksiyon modelleri.
- `src/twin/sim/plots.py`: Tez kalitesinde Matplotlib grafikleri (Türkçe etiketli, PNG/SVG).

### Eklenenler (Faz 3 - Arayüzler)
- `src/twin/api/`: FastAPI REST API servisi, Bearer token yetkilendirme güvenliği ve `docs/openapi.json`.
- `src/twin/ui/`: Streamlit 7 sekmeli 'Senaryo Gezgini' arayüzü.
- `src/twin/cli.py`: Typer `twin` CLI aracı (`fetch-era5`, `qc`, `simulate`, `compare`, `sensitivity`, `export-figures`).
- `server/grafana/dashboards/`: İkiz ve telemetri Grafana panelleri.

### Eklenenler (Faz 4 - Düğüm ve Altyapı)
- `firmware/sulama_node/`: ADS1115 I2C (SCL=D1, SDA=D2), DHT=D5, Röle=D6, VCC=D7 güncellenmiş pin haritası, aktif-LOW açılış güvenliği ve geriye uyumlu MQTT telemetrisi.
- `tools/calibrate_sensor.py`: Gravimetrik kalibrasyon eğrisi uydurma aracı.
- `server/docker-compose.yml`: API ve UI servisleri, InfluxDB saklama süresi ve yedekleme betiği.

### Belgelendirme
- `docs/MODULES.md`: Tüm formüllerin ve denklem numaralarının kaynak tablosu.
- `docs/VERIFICATION.md`: Test edilen / edilmeyen bileşenlerin ayrıntılı doğrulama raporu.
- `OPEN_QUESTIONS.md`: Danışmana ve kurumlara sorulacak açık sorular ve varsayılan parametreler.
