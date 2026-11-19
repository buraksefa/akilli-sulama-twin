# Arayüz belirtimi

Hepsi yalnızca yerel ağda, kimlik doğrulamalı. Hiçbiri İSKİ verisini dışarıya vermez.

## 1. MQTT (mevcut, düğümden sunucuya)

Konular: `sulama/<NODE_ID>/telemetry|status|cmd|ack`. Telemetri JSON'u (mevcut alanlar korunur):

```json
{"node":"node01","seq":42,"up_s":2520,"soil_raw":512,"soil_pct":48.1,"temp_c":22.4,"hum_pct":41,
 "pump_s":0,"rssi":-61,"err":0}
```

Genişleme (geriye uyumlu): `soil_raw_1`, `soil_raw_2`, `soil_vwc_0..2` (kalibrasyondan sonra, m³/m³).
Komutlar (yalnızca MQTT): `PUMP`, `STOP`, `STATUS`. Pompa güvenliği: en fazla 20 sn, en az 60 sn dinlenme.

ThingSpeak 8 alanla sınırlı: mevcut eşleme `field1..8 = soil_raw, soil_pct, temp_c, hum_pct, pump_s,
rssi, seq, err`. Çok kanallı sürümde alan eşlemesi yeniden belirlenip README'ye yazılacak.

## 2. REST API (`src/twin/api`, FastAPI, `Authorization: Bearer <token>`)

| Uç | Yöntem | Amaç |
| --- | --- | --- |
| `/health` | GET | Sağlık ve sürüm |
| `/parks` | GET | Park listesi, alanlar (`parks.geojson`) |
| `/parks/{id}/zones` | GET | Bölgeler (`zones.geojson` varsa; yoksa tek varsayılan bölge) |
| `/weather` | GET | `park_id, start, end` ile ERA5/istasyon serisi ve ETo |
| `/telemetry` | GET | Testbed serisi (InfluxDB), `node, start, end` |
| `/qc` | POST | Seri için kalite raporu ve arıza bayrakları |
| `/simulate` | POST | `{park_id, season, strategy, params}` → günlük seri ve metrikler |
| `/compare` | POST | Birden çok strateji ve CRITIC sıralaması |
| `/sensitivity` | POST | OAT ve Sobol/Morris |
| `/testbed/state` | GET | İkizin tahmini nem/tükenme durumu ve son komut |
| `/testbed/advice` | GET | Önerilen sulama süresi (otomatik gönderme yok, onay gerekir) |

Hata biçimi: `{"error": "...", "detail": "..."}`. OpenAPI şeması otomatik üretilir ve `docs/openapi.json`
olarak saklanır.

## 3. Arayüz (`src/twin/ui`, Streamlit "Senaryo gezgini")

1. **Park ve veri:** harita (poligonlar), alan, veri durumu (hazır/bekliyor).
2. **Hava ve ETo:** ERA5 serisi, PM ve Hargreaves karşılaştırması.
3. **Sensör kalitesi:** seri, bayraklar, sanal sensör yedeği.
4. **Simülasyon:** sezon, strateji, parametre seçimi; nem, Ks, sulama grafikleri.
5. **Karşılaştırma:** strateji tablosu, CRITIC ağırlıkları ve sıralama.
6. **Duyarlılık:** parametre etki grafiği.
7. **Testbed canlı:** son ölçümler, ikiz tahmini, önerilen süre, manuel onay düğmesi.

Tez grafikleri bu arayüzden PNG/SVG olarak dışa aktarılabilmeli (Türkçe etiketli).

## 4. CLI (`twin`, typer)

```
twin fetch-era5 --start 2015-04 --end 2025-10 --park yildiz
twin qc data/raw/serial_log.csv --interval 60
twin simulate --park yildiz --season 2024 --strategy S4
twin compare --park macka --seasons 2015-2025
twin sensitivity --park yildiz --method sobol
twin export-figures --out outputs/figures
```

## 5. Grafana

Provisioning JSON ile: toprak nemi, sıcaklık/nem, hata bayrakları (`err`), pompa süresi, sinyal gücü,
ikiz tahmini ile ölçüm kıyası.
