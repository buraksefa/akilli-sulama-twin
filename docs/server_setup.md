# Ev sunucusu kurulumu (eski ASUS dizüstü)

Amaç: Tezin veri toplama, depolama ve işleme tarafını evdeki eski dizüstüne taşımak. ThingSpeak ikincil
kopya olarak kalır; hassas veri (özellikle İSKİ'den gelecek) bu makineden çıkmaz. Aynı makine yerel
agent işi için de kullanılacak.

> Yazdıklarım standart kurulum adımlarıdır; makinenin donanımını bilmediğim için kapasite rakamları
> tahminidir. Önce 1. adımdaki kontrolü yap, çıktıyı bana yaz, planı ona göre netleştiririz.

## 1. Makineyi tanı (sıfırlamadan önce)

Eski Windows ya da Linux içinden veya bir canlı USB ile:

```bash
lscpu | grep -E 'Model name|^CPU\(s\)'
free -h                    # RAM
lsblk -d -o NAME,SIZE,ROTA,MODEL    # ROTA=1 dönen disk (HDD), 0 SSD
sudo dmidecode -s system-product-name
upower -i $(upower -e | grep BAT) | grep -E 'capacity|energy-full'   # pil sağlığı
```

Karar noktaları:

| Durum | Anlamı |
| --- | --- |
| RAM 4 GB | Yığın çalışır ama yerel model/agent için dar. Mümkünse RAM artır. |
| RAM 8 GB ve üstü | Yığın rahat çalışır, küçük yerel modeller denenebilir. |
| Disk HDD | SSD'ye geçmek (ucuz) hem hız hem dayanıklılık için en iyi yatırım. |
| Pil çok zayıf | Sorun değil; yine de takılı kalacağı için şarj sınırı koy (4. adım). |

Sıfırlamadan önce eski diskten almak istediğin dosyaları yedekle. Diski silmeden önce ASUS'un BIOS
şifresi, açılış sırası ve "AC güç gidip gelince otomatik aç" ayarı olup olmadığına bak.

## 2. İşletim sistemi

Güncel bir Ubuntu Server LTS ya da Debian kararlı sürümü, **tam disk şifrelemesiyle** (LUKS) kur.
Masaüstü ortamı kurma; sunucu ssh ile yönetilir.

- Şifreleme sebebi: İSKİ verisi gizlilik taahhütnamesine tabi olacak ve makine evde, fiziksel olarak
  çalınabilir. Disk şifreliyse çalınma durumunda veri okunmaz.
- Bedeli: elektrik kesilip gelirse makine parola bekler, kendi kendine açılmaz. Bu süre boyunca
  düğümler yerel yedeğe (LittleFS) yazar ve ThingSpeak'e göndermeye devam eder. Gerçek bir kesintisiz
  çalışma gerekiyorsa sonradan TPM ile otomatik açma düşünülür, ama güvenlik düşer.
- Kurulumda: kullanıcı oluştur, ssh sunucusunu aç, ana bilgisayar adı `sulama-sunucu`.

## 3. Güvenlik ve ağ

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y ufw unattended-upgrades chrony
sudo dpkg-reconfigure -plow unattended-upgrades

# ssh: yalnızca anahtarla giriş. Önce anahtarını ekle (ssh-copy-id), sonra:
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl reload ssh

# Güvenlik duvarı: ev ağın 192.168.1.0/24 ise (kendi ağına göre değiştir)
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from 192.168.1.0/24 to any port 22 proto tcp
sudo ufw allow from 192.168.1.0/24 to any port 1883 proto tcp
sudo ufw allow from 192.168.1.0/24 to any port 3000 proto tcp
sudo ufw enable
```

- Modemde sunucuya **sabit IP** (DHCP rezervasyonu) ver. Aynı IP `server/.env` içinde `LAN_BIND_IP` ve
  düğümün `config.h` dosyasında `MQTT_HOST` olacak.
- Modemde **port yönlendirme yapma** (1883, 3000, 8086 ve ssh internete açılmasın).
- Docker bazı durumlarda ufw kurallarını atlayabilir; bu yüzden compose dosyasında portlar yalnızca
  `LAN_BIND_IP`'ye (InfluxDB için 127.0.0.1'e) bağlandı. Kurulumdan sonra başka bir cihazdan `nmap`
  ile hangi portların açık olduğunu kontrol et.

Evin dışından erişim gerekirse **Tailscale** ya da WireGuard kullan (modemde port açmadan). Grafana'ya
telefondan bakmak istersen en kolay yol budur.

## 4. Dizüstüne özel ayarlar

```bash
# Kapak kapanınca uyumasın
sudo sed -i 's/^#\?HandleLidSwitch=.*/HandleLidSwitch=ignore/; s/^#\?HandleLidSwitchExternalPower=.*/HandleLidSwitchExternalPower=ignore/' /etc/systemd/logind.conf
sudo systemctl restart systemd-logind
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

- Pil sürekli şarjda kalırsa şişer. ASUS'un çoğu modelinde şarj sınırı ayarlanabilir:
  `ls /sys/class/power_supply/BAT0/charge_control_end_threshold` dosyası varsa
  `echo 80 | sudo tee /sys/class/power_supply/BAT0/charge_control_end_threshold` (kalıcı yapmak için
  `tlp` ya da bir systemd servisi). Dosya yoksa BIOS'ta şarj sınırı seçeneğine bak; hiçbiri yoksa pili
  çıkarıp doğrudan adaptörle çalıştırmak da bir seçenek (kesintide kapanır, bunu bilerek karar ver).
- Havalandırma deliklerini kapatma; tozunu temizle. Isınma uzun süreli çalışmada asıl risktir.
- Ekran ışığını kapat: `/etc/default/grub` içinde `GRUB_CMDLINE_LINUX_DEFAULT` satırına `consoleblank=60`.

## 5. Docker ve yığın

Docker Engine'i resmi depodan kur (docs.docker.com/engine/install/ubuntu — Debian için ilgili sayfa).
Sonra:

```bash
git clone <depo adresin> akilli-sulama-twin   # ya da zip'i sunucuya kopyala
cd akilli-sulama-twin/server
nano .env.example        # LAN_BIND_IP'yi sunucunun sabit IP'si yap
./scripts/init.sh        # .env üretir, MQTT parolalarını oluşturur
docker compose up -d
docker compose ps        # dört servis "running" olmalı
docker compose logs -f telegraf mosquitto   # hatalar için
```

Doğrulama (düğüm olmadan bile):

```bash
# Bir terminalde dinle
docker compose exec mosquitto mosquitto_sub -u operator -P "$(grep ^MQTT_OPERATOR_PASS .env | cut -d= -f2)" -t 'sulama/#' -v
# Başka terminalde sahte ölçüm yayınla
docker compose exec mosquitto mosquitto_pub -u sulama -P "$(grep ^MQTT_NODE_PASS .env | cut -d= -f2)" \
  -t sulama/test/telemetry -m '{"soil_raw":600,"soil_pct":50.0,"temp_c":22.5,"hum_pct":45.0,"pump_s":0.0,"rssi":-60,"err":0,"seq":1,"up":10}'
```

Grafana: `http://<sunucu-ip>:3000` (kullanıcı `admin`, parola `.env` içindeki `GRAFANA_ADMIN_PASSWORD`).
Explore'da InfluxDB veri kaynağıyla şu Flux sorgusu sahte ölçümü göstermeli:

```
from(bucket: "sulama") |> range(start: -1h) |> filter(fn: (r) => r._measurement == "sulama" and r._field == "soil_pct")
```

Telegraf `null` alanları (DHT hata verirse JSON'da `null` olur) sorunsuz atlıyor mu henüz doğrulamadım;
ilk DHT hatasında `docker compose logs telegraf` çıktısına bak.

## 6. Yedekleme

- Düzenli yedek: InfluxDB için `docker compose exec influxdb influx backup /tmp/yedek` sonra dosyayı
  hosta kopyala; ya da Docker birimlerini tar'la. Yedek diski **şifreli** olsun (restic ya da LUKS).
- Yedeği bir kez geri yükleyerek dene; denenmemiş yedek yedek sayılmaz.
- ThingSpeak zaten ikinci bir kopya; sunucu çökerse son günlerin verisi oradan `tools/thingspeak_fetch.py`
  ile alınabilir.

## 7. İSKİ verisi için kurallar

İSKİ'den veri gelirse (Gizlilik Taahhütnamesi imzalanacak):

1. `/srv/iski-data` gibi ayrı bir dizinde, sahibi sen, izin `700`. Şifreli diskin içinde.
2. **ThingSpeak, bulut depolama, bulut yapay zekâ araçları (sohbet botları dahil) ve e-posta ile
   dışarı gönderme yok.** Taahhütnamede saklama yeri, saklama süresi, imha, kopyalama ve üçüncü kişi
   hükümlerini imzalamadan önce oku; bu kurallar bu belgeden önceliklidir.
3. İşleme sunucuda ya da sunucuya ssh ile bağlanarak yapılır. Ham veriyi dizüstüne indirme.
4. Tezde yalnızca toplulaştırılmış sonuç ve grafikler paylaşılır; ham veri paylaşılmaz.

## 8. Yerel agent işi

Yerel agent'ın ne olduğunu (hangi yazılım, hangi model, ne kadar RAM) bilmiyorum. Genel kurallar:

- Ayrı bir kullanıcı ve ayrı bir Docker Compose projesi olarak çalıştır; sulama yığınıyla karışmasın.
- Docker'da bellek sınırı koy (`mem_limit`) ki bir model yüklemesi InfluxDB'yi öldürmesin.
- Agent'a İSKİ verisi dizinine erişim verme; yalnızca anonim ya da toplulaştırılmış çıktıyı görsün.
- Sunucu 1. adımdaki ölçüme göre yeterli RAM'e sahip değilse agent işini ayrı bir makineye bırak.
