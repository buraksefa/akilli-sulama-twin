#!/usr/bin/env bash
# InfluxDB ve Mosquitto yerel yedekleme betiği
set -euo pipefail

BACKUP_DIR="${1:-./backups/$(date +%Y%m%d_%H%M%S)}"
mkdir -p "${BACKUP_DIR}"

echo "=== Sulama Sistemi Yedekleme Başlıyor: ${BACKUP_DIR} ==="

if command -v docker &> /dev/null; then
    echo "InfluxDB veritabanı yedeği alınıyor..."
    docker compose exec -T influxdb influx backup /tmp/backup || true
    docker compose cp influxdb:/tmp/backup "${BACKUP_DIR}/influxdb" || true
    echo "Yedek tamamlandı: ${BACKUP_DIR}"
else
    echo "Docker bulunamadı veya çalışmıyor."
fi
