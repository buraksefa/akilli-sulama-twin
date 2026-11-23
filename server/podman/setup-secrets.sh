#!/usr/bin/env bash
# rhelsrv üzerinde BURAK çalıştırır (bir kez). MQTT kullanıcıları için rastgele parola üretir:
#   - ~/sulama-twin/server/mosquitto/config/passwd  (Mosquitto, karma olarak)
#   - ~/.config/sulama/devices.env                   (simülatör ve alım servisinin kimliği, chmod 600)
# Parolalar ekrana yazılmaz, komut satırına girmez. Gerçek düğüm kullanıcısı (sulama) için parola
# isteğe bağlı olarak elle girilir: ./setup-secrets.sh --node-user
set -euo pipefail
umask 077
CONF="$HOME/sulama-twin/server/mosquitto/config"
ENVF="$HOME/.config/sulama/devices.env"
mkdir -p "$(dirname "$ENVF")"
if [[ -f "$ENVF" && "${1:-}" != "--force" && "${1:-}" != "--node-user" ]]; then
  echo "Zaten var: $ENVF (yeniden üretmek için --force)"; exit 0
fi
gen() { head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 28; }
SIM_PASS="$(gen)"; ING_PASS="$(gen)"
tmp="$(mktemp)"
printf 'devsim:%s\ningest:%s\n' "$SIM_PASS" "$ING_PASS" > "$tmp"
if [[ "${1:-}" == "--node-user" ]]; then
  read -r -s -p "Gerçek düğüm (kullanıcı 'sulama') parolası: " NODE_PASS; echo
  printf 'sulama:%s\n' "$NODE_PASS" >> "$tmp"
fi
# düz metni konteyner içinde karmaya çevir (parola komut satırına girmez)
podman run --rm -v "$tmp:/tmp/passwd:Z" docker.io/library/eclipse-mosquitto:2 mosquitto_passwd -U /tmp/passwd
install -m 600 "$tmp" "$CONF/passwd" && rm -f "$tmp"
cat > "$ENVF" <<ENV
MQTT_SIM_USER=devsim
MQTT_SIM_PASS=$SIM_PASS
MQTT_INGEST_USER=ingest
MQTT_INGEST_PASS=$ING_PASS
ENV
chmod 600 "$ENVF"
echo "Tamam: $CONF/passwd ve $ENVF yazıldı (parolalar gösterilmedi)."
