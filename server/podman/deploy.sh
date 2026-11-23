#!/usr/bin/env bash
# Mac'ten, ev ağındayken çalıştırılır: kodu rhelsrv'ye kopyalar, imajı derler, quadlet'leri kurar, servisleri başlatır.
#   server/podman/deploy.sh [burak@192.168.1.142]
# İSKİ verisi, ham ERA5, sırlar, .venv ve çıktılar kesinlikle kopyalanmaz (CLAUDE.md §2.1–2.2).
set -euo pipefail
HOST="${1:-burak@192.168.1.142}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
IP="${HOST#*@}"
if ! nc -z -G 3 "$IP" 22 2>/dev/null; then
  echo "rhelsrv ($IP:22) erişilemiyor: Mac ev ağında değil olabilir (Tailscale bu Mac'te engelli)."; exit 1
fi
rsync -az --delete \
  --exclude '.git/' --exclude '.venv/' --exclude 'outputs/' --exclude 'notebooks/' \
  --exclude 'data/iski/' --exclude '*iski*' --exclude 'data/raw/' \
  --exclude '.env' --exclude 'server/.env' --exclude 'server/mosquitto/config/passwd' \
  --exclude 'firmware/sulama_node/config.h' --exclude '*.sqlite*' --exclude 'data/devices/weather_cache.pkl' \
  --exclude '__pycache__/' --exclude '.pytest_cache/' --exclude '.ruff_cache/' --exclude 'CLAUDE.md.bak' \
  "$ROOT/" "$HOST:sulama-twin/"
ssh "$HOST" bash -s <<'REMOTE'
set -euo pipefail
cd ~/sulama-twin
podman build -q -f server/podman/Containerfile -t localhost/sulama-twin:latest .
mkdir -p ~/.config/containers/systemd
cp server/podman/sulama*.container server/podman/sulama.network ~/.config/containers/systemd/
systemctl --user daemon-reload
if [[ ! -f ~/.config/sulama/devices.env || ! -f server/mosquitto/config/passwd ]]; then
  echo "Eksik: önce rhelsrv'de 'bash ~/sulama-twin/server/podman/setup-secrets.sh' çalıştırılmalı."; exit 2
fi
systemctl --user restart sulama-mosquitto sulama-ingest sulama-devsim sulama-ui
sleep 5
systemctl --user --no-pager --lines=0 status sulama-mosquitto sulama-ingest sulama-devsim sulama-ui | grep -E '●|Active:'
REMOTE
echo "Panel: http://$IP:8501  (firewalld'de 8501/tcp ve gerçek düğümler için 1883/tcp açık olmalı)"
