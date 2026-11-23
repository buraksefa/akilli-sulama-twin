# Sensör düğümü platformu (sanal → gerçek)

Durum: 2026-11-23. Amaç, myDevices benzeri ama sade bir cihaz katmanı kurmak. Bugün sanal düğümlerle çalışıyor;
gerçek sensör geldiğinde kod değişmeden aynı hatta bağlanacak.

## 1. Mimari

```
 sanal düğümler (twin devices simulate)  ─┐                        ┌─ SQLite: ölçüm, durum, günlük QC, uyarı
 gerçek düğümler (firmware/sulama_node)  ─┼─► Mosquitto ─► ingest ─┤
                                           │   sulama/<node>/telemetry, /status
                                           └─ (Telegraf → InfluxDB → Grafana, isteğe bağlı)
                                                                    └─► Panel: Cihazlar sayfası + sanal park
```

| Bileşen | Kod | Görev |
|---|---|---|
| Sözleşme | `src/twin/devices/schema.py` | Firmware'in JSON'u (`node, seq, up, ts, soil_raw, soil_pct, soil_vwc, temp_c, hum_pct, pump_s, rssi, err`) ve isteğe bağlı `battery_v`, `sim`. Yayın yalnız `telemetry` ve `status` konularına yapılır. |
| Kayıt | `data/devices/registry.json`, `registry.py` | Düğüm, zon, konum, `source` (`simulated` / `real`). |
| Simülatör | `simulator.py` | Sanal parkı gerçek zamanda yürütür ve 15 dakikada bir ölçüm yayınlar (§2). |
| Alım | `ingest.py` | Şema doğrulama, kayıtsız düğüm tespiti, anlık kontrol, günlük QC ve uyarılar (§3). |
| Depo | `store.py` | SQLite; yol `TWIN_DEVICE_DB`. |
| MQTT | `mqtt.py` | paho-mqtt 2. Kimlik yalnız ortam değişkeninden okunur (`MQTT_SIM_*`, `MQTT_INGEST_*`). |
| Panel | `src/twin/ui/pages/1_Cihazlar.py` | Düğüm listesi, harita, ayrıntı, 48 saatlik grafik, günlük QC ve uyarılar. Canlı depo yoksa DEMO üretir. |
| Kurulum | `server/podman/` | rhelsrv için rootless Podman quadlet'leri ve betikler (§5). |

**Güvenlik:**

- Komut yolu yok: paket `cmd` konusuna yayın yapmaz. `topic_for` bunu reddeder.
- ACL'de `devsim` ve `ingest` kullanıcılarının `cmd` izni yok.
- Testler: `tests/test_devices.py`.

## 2. Sanal düğüm modeli (hepsi `sim: true`, varsayım)

**Gün başı:**

- Open-Meteo'nun 92 günlük geçmişi ve 7 günlük tahminiyle sanal dünya bugünün sabahına getirilir.
  İkiz model + sensör ile, QC açık çalışır.
- İkizin bugünkü zon dozları sabah 05:00'te sanal sisteme uygulanır. Bu sanal bir uygulamadır; gerçek aktüatöre
  hiçbir şey gitmez.

**Gün içi:**

- Hücre açığı ilerler: ETc 06–19 arasına sinüs biçiminde dağıtılır, yağış güne eşit yayılır.
- Okuma = hücre nemi + günlük sensör hatası + kısa dönem gürültü (σ 0,003).
  - Günlük hata, sanal dünyanın sensör modelinden gelir: gürültü, kayma, donma, veri kaybı.
  - Gece yarısı sıçraması olmasın diye hata, dünkü değerden bugünküne gün boyunca doğrusal geçer.
- Ham değer, firmware kalibrasyonunun tersiyle üretilir (kuru 1000, ıslak 400, 0,40 m³/m³; kalibrasyon yapılmadı).

**Diğer kanallar:**

- **Sıcaklık:** en düşük 06:00, en yüksek 15:00 kosinüs eğrisi.
- **Hava nemi:** sıcaklıkla ters orantılı.
- **Pil:** günde 0,004 V düşer.
- **RSSI:** düğümün kendi ortalamasına geri dönen rastgele yürüyüş.

**Dayanıklılık:**

- Open-Meteo yanıt vermezse 3 kez yeniden dener.
- Sonra, bugünü kapsıyorsa diskteki son veriyi kullanır (`TWIN_WEATHER_CACHE`).
- Servis kapanmaz; bir sonraki turda yeniden dener.

## 3. Kalite kontrol ve uyarılar

- **Anlık kontrol (her ileti):** firmware hata bitleri ve fiziksel aralık (VWC 0–0,60). Sonuç `live_qc` alanına
  yazılır.
- **Günlük QC (gün kapanınca):** günün ortalama VWC'si `OnlineSensorQC`'ye verilir (`docs/model/SENSOR_QC.md`,
  kural 1–6).
  - Yeniden başlatmada QC durumu depodan yeniden kurulur.
  - **Kayma testi (kural 7) canlı hatta henüz yok:** açık döngü model referansı alım servisine bağlanmadı.
- **Uyarılar:**

  | Uyarı | Koşul |
  |---|---|
  | Çevrimdışı | 3 aralık boyunca ölçüm yok ya da düğüm `offline` bildirdi |
  | Düşük pil | < 3,4 V; 3,45 V'ta kapanır |
  | Zayıf sinyal | < −85 dBm; −82 dBm'de kapanır |
  | Cihaz hatası | firmware hata biti var |
  | QC reddi | günlük QC okumayı reddetti |
  | Kayıtsız düğüm | kayıtta olmayan düğümden ileti geldi |
  | Bozuk ileti | şemaya uymayan ileti |

  Eşiklerin tümü `TwinConfig.devices` içinde, `assumption` etiketli.

## 4. Gerçek sensörü bağlamak

1. `registry.json` dosyasında düğümün `source` alanını `"real"` yapın (ya da yeni bir satır ekleyin). Simülatör o
   düğümü artık yayınlamaz.
2. Firmware `config.h` içinde `NODE_ID` aynı ad olsun. MQTT kullanıcısı `sulama` olacak (parolası:
   `setup-secrets.sh --node-user`).
3. Alım servisi, panel ve QC değişmez. Satırlardaki `sim` bayrağı kaynağı ayırır.
4. Kalibrasyondan sonra firmware'e `CALIB_SLOPE/INTERCEPT` girilir ve config'teki `soil_raw_*` varsayımları
   ölçülen değerle değiştirilir.

## 5. Çalıştırma

**Yerel (Mac, Docker yok):**

```bash
.venv/bin/twin devices broker --port 18830
```

```bash
.venv/bin/twin devices ingest --port 18830 --anonymous --db /tmp/t.sqlite
```

```bash
.venv/bin/twin devices simulate --port 18830 --anonymous
```

Aracısız demo (son 48 saat):

```bash
.venv/bin/twin devices backfill --hours 48
```

**rhelsrv'ye kurulum.** Kurulum yalnız Mac ev ağındayken yapılabilir; IBM yönetimli Mac'te Tailscale engelli.

- **Hedef:** bsasrv üzerindeki RHEL 9 sanal makinesi, 192.168.1.142, rootless Podman.
- **RAM:** 2 GB ve bir kısmını Open WebUI kullanıyor. Bu yüzden InfluxDB ve Grafana bu kuruluma alınmadı.

Adımlar:

1. Mac'ten kodu kopyala, imajı derle ve quadlet'leri kur:

   ```bash
   server/podman/deploy.sh
   ```

   Bu ilk çalıştırma parola dosyası yoksa durur.
2. rhelsrv'de Burak parolaları üretir. Parolalar ekrana yazılmaz:

   ```bash
   bash ~/sulama-twin/server/podman/setup-secrets.sh
   ```

3. Burak firewalld kapılarını açar (8501 panel, 1883 gerçek düğümler için):

   ```bash
   sudo firewall-cmd --permanent --add-port=8501/tcp --add-port=1883/tcp && sudo firewall-cmd --reload
   ```

4. Mac'ten kurulumu yeniden çalıştır. Servisler başlar; panel `http://192.168.1.142:8501` adresinde açılır:

   ```bash
   server/podman/deploy.sh
   ```

**Kurulumda doğrulanacaklar (henüz denenmedi):**

- Rootless Podman'da Mosquitto, 600 izinli parola dosyasını okuyabiliyor mu?
- 8501 kapısı rhelsrv'de boş mu?
- Dört konteyner birlikte RAM'e sığıyor mu?

## 6. Sınırlılıklar

- Gün içi nem eğrisi basit bir varsayımdır. Yağışın saati bilinmiyor (günlük veri), sulama saati sabit.
- Sıcaklık ve hava nemi sentetik eğridir; DHT okuması değildir.
- Kayma testi (QC kural 7) canlı hatta yok.
- İkiz henüz canlı depodan beslenmiyor: sanal park ekranı kendi simülasyonunu kullanıyor. Sıradaki adım, ikizin
  sabah kararını alım deposundaki dünkü günlük ortalamalardan almasıdır.
