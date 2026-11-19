# Ubuntu Server kurulumu (Wi-Fi, şifreli disk, ssh anahtarı)

Hedef: eski ASUS dizüstü, genel amaçlı ev sunucusu. Bu proje (sulama) onun üzerinde çalışan
servislerden yalnızca biri. Bu yüzden kullanıcı ve ana makine adı projeye özel değil.

> Bu dosyalar kurulum yapar ama ben (Claude) dizüstüne uzaktan erişemem. Kurulumu USB ile sen
> başlatırsın, sonrasını birlikte yaparız. Kurulum dosyası **hiç denenmedi**; alanları donanımına göre
> ilk denemede düzeltmen gerekebilir.

## 0. Önce kontrol et

- Dizüstündeki dosyaları yedekle (kurulum diskin tamamını siler).
- Laptop özelliklerini (model, RAM, disk türü) bana ver; disk adı ve Wi-Fi çipi buna göre kontrol edilir.
- Wi-Fi çipi Intel ise genelde sorunsuz, Realtek/Broadcom ise kurulum ortamında tanınmayabilir.
  Ethernet kablosu ve bir adaptör ilk kurulum için yedek plan olsun.
- BIOS'ta (açılışta F2): Secure Boot açık kalabilir, USB'den açılışı etkinleştir, "Fast Boot" kapalı olsun.
  Pil şarj sınırı varsa (ASUS: "Battery Health Charging") %60 yap, pil sürekli %100'de kalmasın.

## 1. SSH anahtarı üret (Windows PowerShell)

```powershell
ssh-keygen -t ed25519 -C "burak-ev-sunucu"
```

Dosya yolu için Enter, parola (passphrase) sorusuna bir parola yaz. Parola önerilir: bilgisayarın
çalınırsa anahtar tek başına işe yaramaz.
İki dosya oluşur (`C:\Users\<sen>\.ssh\`):

- `id_ed25519` **özel anahtar**: kimseyle paylaşma, bana da yapıştırma.
- `id_ed25519.pub` **genel anahtar**: tek satır, `ssh-ed25519 AAAA... burak-ev-sunucu`. Bunu
  `user-data` içindeki `<SSH_PUBLIC_KEY>` yerine koy. Genel anahtar paylaşılabilir.

```powershell
type $env:USERPROFILE\.ssh\id_ed25519.pub
```

## 2. user-data alanlarını doldur

`server/autoinstall/user-data` içinde şunları değiştir:

| Alan | Ne yazılır |
| --- | --- |
| `<WIFI_ADI>`, `<WIFI_PAROLASI>` | Ev Wi-Fi'si (5 GHz'de sorun çıkarsa 2,4 GHz). Gizli ağ değilse yeter |
| `<HOSTNAME>` | Örn. `ev-sunucu` |
| `<KULLANICI>` | Örn. `burak` (iki yerde: `identity` ve `late-commands` sonu) |
| `<PAROLA_HASH>` | `openssl passwd -6` çıktısı (WSL'de ya da Git Bash'te çalışır). sudo parolan olur |
| `<SSH_PUBLIC_KEY>` | 1. bölümdeki tek satır |
| `<GECICI_DISK_SIFRESI>` | Uzun bir geçici parola; ilk girişte değiştireceksin |

Ağ bloğu (`192.168.0.0/16`) ev ağını kapsıyor; modemin 192.168.x.x vermiyorsa düzelt.

## 3. USB hazırla ve kur

1. Ubuntu Server 24.04 LTS ISO'sunu indir, Rufus ile (GPT/UEFI) USB'ye yaz.
2. USB'nin veri bölümüne ya da ikinci bir küçük USB'ye `user-data` ve `meta-data` dosyalarını koy.
   Ubuntu'nun yönergesi: etiketi `CIDATA` olan bir FAT32 birim, kökünde bu iki dosya.
3. Dizüstünü USB'den aç. GRUB menüsünde `e` ile düzenleme, `linux` satırının sonuna
   `autoinstall` ekle, `Ctrl+X`. (Eklemezsen kurucu "diski silinsin mi" diye onay ister; bu istenen güvenlik.)
4. Kurulum bitince yeniden başlar; açılışta disk şifresini sorar. USB'yi çıkar.

## 4. İlk giriş ve sertleştirme

```powershell
ssh <KULLANICI>@<sunucu-ip>      # IP için modem arayüzüne bak; sonra modemde sabit IP ver
```

```bash
sudo cryptsetup luksChangePassword /dev/<sifreli-bolum>   # lsblk -f ile bul
sudo nano /etc/ssh/sshd_config.d/99-hardening.conf         # PermitRootLogin no, PasswordAuthentication no
sudo ufw status verbose
sudo apt update && sudo apt full-upgrade
sudo systemctl status docker
```

Sonra `docs/server_setup.md` içindeki proje kurulumuna (Docker yığını, `init.sh`) geç.

## 5. Genel amaçlı sunucu için yapı kuralları

- **Ayrı kullanıcılar:** ana kullanıcın yönetici. Yerel agent için ayrı, sudo'suz bir kullanıcı aç
  (örn. `agent`). `docker` grubuna **ekleme**, çünkü bu grup fiilen root yetkisi verir.
- **İSKİ verisi:** `/srv/iski-data`, sahibi yalnızca sana ait (mod 700). Agent kullanıcısı okuyamaz.
  Agent'ın modeli bulut tabanlıdır; dosya içeriği okunursa Anthropic API'sine gider.
- **Her projeye ayrı klasör ve ayrı Docker Compose proje adı;** portlar çakışmasın.
- **Yedek:** LUKS disk ayrı bir fiziksel yedek diske (harici USB) şifreli yedeklenmeli. Yalnızca aynı
  dizüstündeki ikinci bölüm yedek sayılmaz.
- **Uzaktan erişim:** modemde port yönlendirme yapma. Dışarıdan erişim için Tailscale ya da WireGuard.
- **Her açılışta disk şifresi:** elektrik kesilince sunucu şifre beklerken durur. Düğüm verisi bu sürede
  LittleFS'e ve ThingSpeak'e gider. Sık kesinti oluyorsa sonraki adımda TPM ile otomatik açma ya da
  Dropbear ile uzaktan şifre girişi konuşulabilir.
- **Wi-Fi sunucu notu:** MQTT için kablo daha güvenilirdir. Wi-Fi kalıcı olacaksa modeme yakın yerleştir,
  güç tasarrufunu kapat (`iw dev wlan0 set power_save off`).
