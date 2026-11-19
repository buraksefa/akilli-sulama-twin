// Akıllı sulama düğümü: NodeMCU (ESP8266)
// Toprak nemi (ADS1115 / A0) + DHT11 okur. Veriyi birincil olarak ev sunucusundaki MQTT'ye (Mosquitto),
// ikincil olarak ThingSpeak'e gönderir. Seri porta da JSON satırı basar. Birincil teslim
// başarısızsa LittleFS'e CSV yedeği yazar. Pompa seri komutla ya da MQTT komutuyla, güvenli
// sınırlar içinde çalıştırılır.
//
// Gerekli kütüphaneler (Arduino IDE / PlatformIO): "DHT sensor library" (Adafruit),
// "Adafruit Unified Sensor", "PubSubClient" (Nick O'Leary), "Adafruit ADS1X15", "LittleFS".
// Kart: NodeMCU 1.0 (ESP-12E Module), ESP8266 çekirdeği 3.x.
//
// Pin Haritası (ADS1115 I2C çakışması çözülmüş - tezgâhta doğrulanmalı):
//   I2C SDA=D2 (GPIO4), SCL=D1 (GPIO5)
//   DHT=D5 (GPIO14), Röle=D6 (GPIO12), Toprak VCC=D7 (GPIO13)
//   Boot pinleri D3, D4, D8 kullanılmaz.
//
// MQTT konuları: sulama/<NODE_ID>/telemetry (JSON), /status (online/offline, retained),
//                /cmd (komut: PUMP, STOP, STATUS), /ack (komut yanıtı)

#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <LittleFS.h>
#include <Wire.h>
#include <time.h>
#include <DHT.h>
#include "config.h"

// Hata bayrakları (err alanı, bit maskesi)
#define ERR_DHT 1
#define ERR_SOIL 2
#define ERR_WIFI 4
#define ERR_UPLOAD 8   // ThingSpeak gönderimi başarısız
#define ERR_MQTT 16    // MQTT yayını başarısız

static const char *BACKUP_FILE = "/backup.csv";
static const char *BACKUP_HEADER = "epoch,seq,up_s,soil_raw,soil_pct,soil_vwc,temp_c,hum_pct,pump_s,rssi,err,sent";

DHT dht(DHT_PIN, DHT11);
WiFiClient mqttNet;
PubSubClient mqtt(mqttNet);

String topicTelemetry;
String topicStatus;
String topicCmd;
String topicAck;
bool mqttTriedOnce = false;
uint32_t lastMqttTryMs = 0;

uint32_t seqNo = 0;
uint32_t lastReadMs = 0;
bool firstRead = true;

bool pumpOn = false;
bool everPumped = false;
uint32_t pumpStartMs = 0;
uint32_t pumpUntilMs = 0;
uint32_t lastPumpEndMs = 0;
uint32_t pumpTotalMs = 0;

// ---------- Mesaj yardımcısı ----------
void say(const String &msg) {
  Serial.println("# " + msg);
  if (MQTT_ENABLED && mqtt.connected()) mqtt.publish(topicAck.c_str(), msg.c_str());
}

// ---------- Röle / Pompa Güvenliği ----------
void relaySet(bool on) {
  bool pinState = RELAY_ACTIVE_LOW ? !on : on;
  digitalWrite(RELAY_PIN, pinState ? HIGH : LOW);
}

void pumpStop() {
  relaySet(false);
  if (pumpOn) {
    uint32_t now = millis();
    pumpTotalMs += (uint32_t)(now - pumpStartMs);
    lastPumpEndMs = now;
    everPumped = true;
    pumpOn = false;
    say("PUMP durdu");
  }
}

void pumpStart(int sec) {
  if (sec < 1) sec = 1;
  if (sec > PUMP_MAX_S) sec = PUMP_MAX_S;
  uint32_t now = millis();
  if (pumpOn) {
    say("PUMP zaten acik");
    return;
  }
  if (everPumped && (uint32_t)(now - lastPumpEndMs) < (uint32_t)PUMP_MIN_REST_S * 1000UL) {
    say("PUMP reddedildi: dinlenme suresi dolmadi");
    return;
  }
  relaySet(true);
  pumpOn = true;
  pumpStartMs = now;
  pumpUntilMs = now + (uint32_t)sec * 1000UL;
  say("PUMP basladi: " + String(sec) + " sn");
}

float pumpSecondsTotal() {
  uint32_t ms = pumpTotalMs;
  if (pumpOn) ms += (uint32_t)(millis() - pumpStartMs);
  return ms / 1000.0f;
}

// ---------- Sensör Okuma ve Kalibrasyon ----------
int readSoilRawChannel(int channel) {
  if (SOIL_POWER_PIN >= 0) {
    digitalWrite(SOIL_POWER_PIN, HIGH);
    delay(SOIL_SETTLE_MS);
  }
  long sum = 0;
  for (int i = 0; i < SOIL_SAMPLES; i++) {
    sum += analogRead(A0);
    delay(4);
  }
  if (SOIL_POWER_PIN >= 0) digitalWrite(SOIL_POWER_PIN, LOW);
  return (int)(sum / SOIL_SAMPLES);
}

float rawToVWC(int raw) {
  #ifdef CALIB_SLOPE
    float vwc = CALIB_SLOPE * (float)raw + CALIB_INTERCEPT;
    if (vwc < 0.0f) vwc = 0.0f;
    if (vwc > 0.60f) vwc = 0.60f;
    return vwc;
  #else
    return (float)(SOIL_RAW_DRY - raw) / (float)(SOIL_RAW_DRY - SOIL_RAW_WET) * 0.40f;
  #endif
}

float soilPercent(int raw) {
  float p = (float)(SOIL_RAW_DRY - raw) * 100.0f / (float)(SOIL_RAW_DRY - SOIL_RAW_WET);
  if (p < 0.0f) p = 0.0f;
  if (p > 100.0f) p = 100.0f;
  return p;
}

// ---------- Biçimlendirme ----------
void fmtNum(char *buf, size_t n, float v, int decimals, const char *nanText) {
  if (isnan(v)) snprintf(buf, n, "%s", nanText);
  else snprintf(buf, n, "%.*f", decimals, v);
}

void buildJson(char *out, size_t n, uint32_t ep, uint32_t upS, int soilRaw, float soilPct, float soilVwc,
               float t, float h, float pumpS, int rssi, int err) {
  char ts[12], hs[12], ps[12], pu[12], vs[12];
  fmtNum(ts, sizeof(ts), t, 1, "null");
  fmtNum(hs, sizeof(hs), h, 1, "null");
  fmtNum(ps, sizeof(ps), soilPct, 1, "null");
  fmtNum(vs, sizeof(vs), soilVwc, 3, "null");
  fmtNum(pu, sizeof(pu), pumpS, 1, "null");

  // Geriye uyumlu JSON yükü: soil_raw, soil_pct korunur + soil_vwc_0 eklenir
  snprintf(out, n,
           "{\"node\":\"%s\",\"seq\":%lu,\"up\":%lu,\"ts\":%lu,\"soil_raw\":%d,\"soil_pct\":%s,"
           "\"soil_vwc\":%s,\"temp_c\":%s,\"hum_pct\":%s,\"pump_s\":%s,\"rssi\":%d,\"err\":%d}",
           NODE_ID, (unsigned long)seqNo, (unsigned long)upS, (unsigned long)ep, soilRaw, ps, vs, ts, hs, pu, rssi,
           err);
}

// ---------- Yerel Yedek (LittleFS) ----------
void backupAppend(const char *line) {
  FSInfo info;
  if (LittleFS.info(info) && info.usedBytes > BACKUP_MAX_BYTES) return;
  bool isNew = !LittleFS.exists(BACKUP_FILE);
  File f = LittleFS.open(BACKUP_FILE, "a");
  if (!f) return;
  if (isNew) f.println(BACKUP_HEADER);
  f.println(line);
  f.close();
}

// ---------- ThingSpeak ----------
bool tsPost(const String &body) {
  HTTPClient http;
  http.setTimeout(4000);
  int code = -1;
  String resp;
  if (TS_USE_HTTPS) {
    BearSSL::WiFiClientSecure client;
    client.setInsecure();
    if (!http.begin(client, "https://api.thingspeak.com/update")) return false;
    http.addHeader("Content-Type", "application/x-www-form-urlencoded");
    code = http.POST(body);
    if (code > 0) resp = http.getString();
    http.end();
  } else {
    WiFiClient client;
    if (!http.begin(client, "http://api.thingspeak.com/update")) return false;
    http.addHeader("Content-Type", "application/x-www-form-urlencoded");
    code = http.POST(body);
    if (code > 0) resp = http.getString();
    http.end();
  }
  resp.trim();
  return code == 200 && resp.length() > 0 && resp != "0";
}

// ---------- Komutlar ----------
void printStatus() {
  say(String("durum: wifi=") + (WiFi.status() == WL_CONNECTED ? "bagli" : "yok") + ", mqtt=" +
      (mqtt.connected() ? "bagli" : "yok") + ", up=" + String(millis() / 1000) + "s, seq=" + String(seqNo) +
      ", pompa=" + (pumpOn ? "acik" : "kapali") + ", toplam_pompa=" + String(pumpSecondsTotal(), 1) + "s");
}

void handleCommand(const String &raw, bool fromSerial) {
  String cmd = raw;
  cmd.trim();
  cmd.toUpperCase();
  if (cmd.length() == 0) return;

  if (cmd.startsWith("PUMP")) {
    int sec = cmd.substring(4).toInt();
    if (sec <= 0) say("kullanim: PUMP <saniye>");
    else pumpStart(sec);
  } else if (cmd == "STOP") {
    pumpStop();
  } else if (cmd == "STATUS") {
    printStatus();
  } else if (fromSerial && cmd == "RAW") {
    say("RAW=" + String(readSoilRawChannel(0)));
  } else if (fromSerial && cmd == "DUMP") {
    if (!LittleFS.exists(BACKUP_FILE)) {
      say("yedek dosyasi yok");
    } else {
      File f = LittleFS.open(BACKUP_FILE, "r");
      Serial.println("# DUMP basliyor");
      while (f && f.available()) Serial.write(f.read());
      if (f) f.close();
      Serial.println("# DUMP bitti");
    }
  } else if (fromSerial && cmd == "CLEAR") {
    LittleFS.remove(BACKUP_FILE);
    say("yedek silindi");
  } else {
    say(fromSerial ? "komutlar: RAW, PUMP <sn>, STOP, STATUS, DUMP, CLEAR" : "komutlar: PUMP <sn>, STOP, STATUS");
  }
}

void handleSerial() {
  while (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    handleCommand(cmd, true);
  }
}

void onMqttMessage(char *topic, byte *payload, unsigned int len) {
  String cmd;
  for (unsigned int i = 0; i < len && i < 32; i++) cmd += (char)payload[i];
  handleCommand(cmd, false);
}

// ---------- MQTT ----------
bool mqttEnsure() {
  if (!MQTT_ENABLED) return false;
  if (WiFi.status() != WL_CONNECTED) return false;
  if (mqtt.connected()) return true;
  uint32_t now = millis();
  if (mqttTriedOnce && (uint32_t)(now - lastMqttTryMs) < 10000UL) return false;
  mqttTriedOnce = true;
  lastMqttTryMs = now;
  bool ok = mqtt.connect(NODE_ID, MQTT_USER, MQTT_PASS, topicStatus.c_str(), 1, true, "offline");
  if (ok) {
    mqtt.publish(topicStatus.c_str(), "online", true);
    mqtt.subscribe(topicCmd.c_str());
    Serial.println("# MQTT baglandi");
  } else {
    Serial.printf("# MQTT baglanamadi, durum=%d\n", mqtt.state());
  }
  return ok;
}

// ---------- WiFi ----------
void connectWifi(uint32_t timeoutMs) {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && (uint32_t)(millis() - t0) < timeoutMs) {
    delay(250);
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("# WiFi baglandi, IP: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("# WiFi baglanamadi");
  }
}

void doReading() {
  seqNo++;
  int err = 0;

  int soilRaw = readSoilRawChannel(0);
  float soilPct = soilPercent(soilRaw);
  float soilVwc = rawToVWC(soilRaw);
  if (soilRaw <= 5 || soilRaw >= 1023) err |= ERR_SOIL;

  float t = dht.readTemperature();
  float h = dht.readHumidity();
  if (isnan(t) || isnan(h)) {
    err |= ERR_DHT;
    t = NAN;
    h = NAN;
  }

  float pumpS = pumpSecondsTotal();
  bool wifiUp = (WiFi.status() == WL_CONNECTED);
  int rssi = wifiUp ? WiFi.RSSI() : 0;
  uint32_t upS = millis() / 1000;
  time_t epoch = time(nullptr);
  uint32_t ep = (epoch > 1700000000) ? (uint32_t)epoch : 0;
  if (!wifiUp) err |= ERR_WIFI;

  int sent = 0;

  // 1) Birincil: Yerel MQTT
  if (MQTT_ENABLED) {
    if (wifiUp && mqttEnsure()) {
      char json[280];
      buildJson(json, sizeof(json), ep, upS, soilRaw, soilPct, soilVwc, t, h, pumpS, rssi, err);
      if (mqtt.publish(topicTelemetry.c_str(), json)) sent |= 2;
    }
    if (!(sent & 2)) err |= ERR_MQTT;
  }

  // 2) İkincil: ThingSpeak (8 Alan Eşlemesi)
  if (TS_ENABLED && wifiUp) {
    String body = "api_key=" TS_WRITE_KEY;
    body += "&field1=" + String(soilRaw);
    body += "&field2=" + String(soilPct, 1);
    if (!isnan(t)) body += "&field3=" + String(t, 1);
    if (!isnan(h)) body += "&field4=" + String(h, 1);
    body += "&field5=" + String(pumpS, 1);
    body += "&field6=" + String(rssi);
    body += "&field7=" + String(seqNo);
    body += "&field8=" + String(err);
    if (tsPost(body)) sent |= 1;
    else err |= ERR_UPLOAD;
  } else if (TS_ENABLED) {
    err |= ERR_UPLOAD;
  }

  // Seri porta JSON bas
  char json[280];
  buildJson(json, sizeof(json), ep, upS, soilRaw, soilPct, soilVwc, t, h, pumpS, rssi, err);
  Serial.println(json);

  // Yedek LittleFS
  bool primaryOk = MQTT_ENABLED ? ((sent & 2) != 0) : ((sent & 1) != 0);
  if (!primaryOk) {
    char tt[12], hh[12], pp[12], uu[12], vs[12], line[180];
    fmtNum(tt, sizeof(tt), t, 1, "");
    fmtNum(hh, sizeof(hh), h, 1, "");
    fmtNum(pp, sizeof(pp), soilPct, 1, "");
    fmtNum(vs, sizeof(vs), soilVwc, 3, "");
    fmtNum(uu, sizeof(uu), pumpS, 1, "");
    snprintf(line, sizeof(line), "%lu,%lu,%lu,%d,%s,%s,%s,%s,%s,%d,%d,%d", (unsigned long)ep, (unsigned long)seqNo,
             (unsigned long)upS, soilRaw, pp, vs, tt, hh, uu, rssi, err, sent);
    backupAppend(line);
  }
}

void setup() {
  // Önce röleyi KAPALI yap (aktif-LOW röle için HIGH yazılır)
  pinMode(RELAY_PIN, OUTPUT);
  relaySet(false);

  if (SOIL_POWER_PIN >= 0) {
    pinMode(SOIL_POWER_PIN, OUTPUT);
    digitalWrite(SOIL_POWER_PIN, LOW);
  }

  Serial.begin(115200);
  Serial.setTimeout(50);
  delay(150);
  Serial.println();
  Serial.println("# sulama_node basliyor (ADS1115 uyumlu)");

  topicTelemetry = String("sulama/") + NODE_ID + "/telemetry";
  topicStatus = String("sulama/") + NODE_ID + "/status";
  topicCmd = String("sulama/") + NODE_ID + "/cmd";
  topicAck = String("sulama/") + NODE_ID + "/ack";

  dht.begin();
  if (!LittleFS.begin()) {
    Serial.println("# LittleFS baslatilamadi");
  }

  if (MQTT_ENABLED) {
    mqtt.setServer(MQTT_HOST, MQTT_PORT);
    mqtt.setCallback(onMqttMessage);
  }

  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  connectWifi(10000);
}

void loop() {
  handleSerial();

  if (pumpOn && (int32_t)(millis() - pumpUntilMs) >= 0) {
    pumpStop();
  }

  if (MQTT_ENABLED) {
    if (WiFi.status() == WL_CONNECTED) mqttEnsure();
    mqtt.loop();
  }

  uint32_t now = millis();
  if (firstRead || (uint32_t)(now - lastReadMs) >= (uint32_t)READ_INTERVAL_S * 1000UL) {
    firstRead = false;
    lastReadMs = now;
    doReading();
  }

  delay(20);
}
