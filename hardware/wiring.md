# Donanım ve Bağlantı Şeması

Bu belge Robotistan "NodeMCU IoT Proje Geliştirme Seti" ve ek ADS1115 (I2C) ADC genişleme kartına göredir.

## Kullanılan ve Kullanılmayan Parçalar

| Parça | Durum | Not |
| --- | --- | --- |
| NodeMCU V3 LoLin (ESP8266, CH340) | Kullanılıyor | USB'den hem güç hem seri çıkış |
| Toprak nemi sensörü (Kapasitif / Direnç) | Kullanılıyor | ADS1115 A0 veya NodeMCU A0 |
| ADS1115 16-bit I2C ADC Kartı | Opsiyonel / Tezgâh | Çoklu toprak sensörü (D1=SCL, D2=SDA) |
| DHT11 kartı | Kullanılıyor | D5 pini (Hava sıcaklığı ve nemi) |
| 2 kanallı 5 V röle kartı | Kullanılıyor | D6 pini (Pompa anahtarlama, Aktif-LOW) |
| Mini dalgıç pompa 6 V | Kullanılıyor | Ayrı 6 V pil/adaptör beslemesi |
| Breadboard, jumper kablolar | Kullanılıyor | |

## Güncellenmiş Pin Tablosu (Pin Çakışması Giderilmiş)

ADS1115'in varsayılan I2C pinleri (SCL=D1, SDA=D2) röle ve DHT ile çakışıyordu. Yeni doğrulanmış harita:

| Sinyal | NodeMCU Pini | GPIO | Bağlanacağı Yer | Not |
| --- | --- | --- | --- | --- |
| I2C SCL | D1 | GPIO5 | ADS1115 SCL | I2C Saat hattı |
| I2C SDA | D2 | GPIO4 | ADS1115 SDA | I2C Veri hattı |
| DHT11 Veri | D5 | GPIO14 | DHT11 DATA / S | Sıcaklık ve Nem |
| Röle Kanal 1 | D6 | GPIO12 | Röle IN1 | Aktif-LOW (Açılışta HIGH) |
| Toprak Sensörü VCC | D7 | GPIO13 | Sensör Güç VCC | Korozyon önleyici anahtarlı güç |
| Toprak Nemi (Analog) | A0 | ADC0 | Sensör AO | Tek sensör veya ADS1115 A0..A3 |
| 3.3V / 5V | 3V3 / VIN | - | VCC hatları | DHT11/Sensör -> 3V3, Röle -> VIN (5V) |
| Toprak | GND | - | Ortak GND | Tüm modüller ortak GND |

**Kaçınılan Boot Pinleri:**
- D3 (GPIO0), D4 (GPIO2), D8 (GPIO15) açılış durumunu (Flash/Boot modu) belirlediği için hiçbir çevre birimine bağlanmamıştır.

## Röle ve Pompa Güvenlik Kuralları

1. **Açılış Güvenliği (Boot Safe):** Röle aktif-LOW olduğundan, ESP8266 açılışında `setup()` fonksiyonunda pin çıkış yapılmadan önce `HIGH` seviyesine çekilerek pompanın açılışta istemsizce darbe alması (pulse) engellenir.
2. **Yazılımsal Pompa Limitleri:** Tek bir komutta azami çalışma süresi `20 saniye`, iki sulama arası asgari dinlenme süresi `60 saniye` olarak kısıtlanmıştır (`config.h`).
3. **Bağımsız Güç:** Mini dalgıç pompa asla NodeMCU'nun 3V3 hattından veya USB 5V hattından beslenmez; ayrı 6V pil/adaptör kullanılır. Röle COM ve NO kontakları bu bağımsız devreyi anahtarlar.

## Gravimetrik Kalibrasyon (Kurutarak Tartma)

1. Toprak çekirdeği silindir hacmi $V_{core}$ (cm³) ölçülür.
2. Kademeli olarak ıslatılan toprak örneğinde sensör ham ADC değeri ($raw$) kaydedilir.
3. Yaş toprak tartılır ($W_{wet}$), ardından etüvde 105°C'de 24 saat kurutulup kuru ağırlığı ($W_{dry}$) tartılır.
4. Hacimsel su içeriği hesaplanır:
   $$\theta = \frac{W_{wet} - W_{dry}}{\rho_w \cdot V_{core}} \quad [\text{m}^3/\text{m}^3]$$
5. `tools/calibrate_sensor.py` betiği çalıştırılarak kalibrasyon eğrisi $raw \to \theta$ katsayıları üretilir ve `config.h` içerisindeki `CALIB_SLOPE` ve `CALIB_INTERCEPT` alanlarına yazılır.
