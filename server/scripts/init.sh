#!/usr/bin/env bash
# İlk kurulum: .env üretir, MQTT parola dosyasını oluşturur.
# Gereksinim: docker, openssl, sudo. Çalıştırma: cd server && ./scripts/init.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  # Her CHANGE_ME için ayrı rastgele değer üret
  while grep -q CHANGE_ME .env; do
    secret="$(openssl rand -hex 16)"
    sed -i "0,/CHANGE_ME/s//${secret}/" .env
  done
  echo ".env oluşturuldu (parolalar rastgele üretildi). LAN_BIND_IP değerini kontrol et."
else
  echo ".env zaten var, değiştirilmedi."
fi

# shellcheck disable=SC1091
set -a; . ./.env; set +a

CONF_DIR="$PWD/mosquitto/config"
rm -f "$CONF_DIR/passwd"

first=1
for pair in \
  "${MQTT_NODE_USER}:${MQTT_NODE_PASS}" \
  "${MQTT_TELEGRAF_USER}:${MQTT_TELEGRAF_PASS}" \
  "${MQTT_OPERATOR_USER}:${MQTT_OPERATOR_PASS}"; do
  user="${pair%%:*}"
  pass="${pair#*:}"
  if [ "$first" = 1 ]; then flag="-c -b"; first=0; else flag="-b"; fi
  # shellcheck disable=SC2086
  docker run --rm -v "$CONF_DIR:/mosquitto/config" eclipse-mosquitto:2 \
    mosquitto_passwd $flag /mosquitto/config/passwd "$user" "$pass"
done

# Mosquitto konteyner kullanıcısı (uid 1883) parola ve acl dosyalarını okuyabilmeli, başkası değil.
sudo chown 1883:1883 "$CONF_DIR/passwd" "$CONF_DIR/acl"
sudo chmod 0640 "$CONF_DIR/passwd" "$CONF_DIR/acl"

echo "Tamam. Sıradaki: docker compose up -d"
echo "Düğümün config.h dosyasına MQTT_USER=${MQTT_NODE_USER} ve .env içindeki MQTT_NODE_PASS değerini yaz."
