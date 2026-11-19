// config.example.h -> config.h olarak kopyala ve doldur. config.h git'e girmez (.gitignore).
#pragma once

// ---- Düğüm kimliği (birden fazla düğümde farklı olmalı, MQTT konularında kullanılır) ----
#define NODE_ID "node01"

// ---- Wi-Fi ----
#define WIFI_SSID "EV_AGI_ADI"
#define WIFI_PASS "WIFI_SIFRESI"

// ---- Yerel MQTT (ev sunucusu, birincil teslim) ----
// Sunucuya modemden SABİT IP ver (DHCP rezervasyonu), buraya onu yaz.
#define MQTT_ENABLED true
#define MQTT_HOST "192.168.1.50"
#define MQTT_PORT 1883
#define MQTT_USER "sulama"
#define MQTT_PASS "MQTT_SIFRESI"

// ---- ThingSpeak (bulut, ikincil teslim) ----
#define TS_ENABLED true
// Write API Key: kanalın "API Keys" sekmesinden.
#define TS_WRITE_KEY "THINGSPEAK_WRITE_KEY"
#define TS_USE_HTTPS true

// ---- Yeni Pin Haritası (ADS1115 I2C çakışması çözülmüş - tezgâhta doğrulanmalı) ----
// D1=SCL (GPIO5), D2=SDA (GPIO4) -> ADS1115 I2C
// D5=DHT11 (GPIO14), D6=Röle (GPIO12), D7=Toprak Güç (GPIO13)
// Boot pinleri D3 (GPIO0), D4 (GPIO2), D8 (GPIO15) KULLANILMAZ!
#define I2C_SDA_PIN D2
#define I2C_SCL_PIN D1
#define DHT_PIN D5
#define RELAY_PIN D6
#define SOIL_POWER_PIN D7   // -1: sensör sürekli 3V3'te
#define SOIL_SETTLE_MS 50

// ---- ADS1115 Desteği (Çok Kanallı Toprak Nemi) ----
#define USE_ADS1115 true
#define ADS1115_I2C_ADDR 0x48

// ---- Röle Güvenliği ----
// Aktif-LOW röleler için açılışta HIGH sürülerek rölenin KAPALI kalması sağlanır.
#define RELAY_ACTIVE_LOW true

// ---- Toprak Nemi Kalibrasyon Katsayıları (Gravimetrik Kalibrasyon) ----
// theta_vwc = CALIB_SLOPE * raw + CALIB_INTERCEPT (veya kuru/ıslak yüzde)
#define SOIL_RAW_DRY 1000   // Kuru hava referansı
#define SOIL_RAW_WET 400    // Su referansı
#define CALIB_SLOPE -0.00052f
#define CALIB_INTERCEPT 0.520f
#define SOIL_SAMPLES 16

// ---- Zamanlama ----
#define READ_INTERVAL_S 60

// ---- Pompa Güvenlik Sınırları ----
#define PUMP_MAX_S 20       // Tek komutta azami çalışma süresi (sn)
#define PUMP_MIN_REST_S 60  // İki çalışma arası asgari dinlenme süresi (sn)

// ---- Yerel Yedek (LittleFS) ----
#define BACKUP_MAX_BYTES 200000
