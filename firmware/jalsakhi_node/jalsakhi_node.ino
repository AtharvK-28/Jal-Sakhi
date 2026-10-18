/*
  JalSakhi tap node: firmware for ESP32 (Arduino core 2.x / 3.x, no extra libraries)

  The node reports the pressure and flow at one household tap every two seconds. On the server it
  stands in for a metered home in the network twin, so the estimator, the fault detectors and the
  alerts react to this board exactly as they would to a node in the field.

  SENSORS
    SENSORS_FITTED 0 (default): no sensors needed. The board plays a tap. Each press of the BOOT
      button moves to the next state: tap open -> pipe pinched -> tap closed -> open again. The
      on-board LED is off, blinking, or on to match. Readings are generated on the board and sent
      marked "emulated", so the dashboard never presents them as measurements.
    SENSORS_FITTED 1: reads a pressure transducer and a flow sensor (wiring below). Calibrate both
      against a reference before trusting a number.

  UPLINK
    Wi-Fi: fill in WIFI_SSID, WIFI_PASSWORD and SERVER_URL. The board posts to /api/telemetry itself.
    USB:   leave WIFI_SSID empty. Every reading is also printed on the serial port as a line that
           starts with "JS1 "; run  python firmware/usb_bridge.py  on the laptop and it forwards them.
           Use this when the venue Wi-Fi cannot be trusted.

  Readings that cannot be delivered over Wi-Fi wait in a ring buffer and are re-sent, oldest first,
  with exponential backoff. Every reading has a unique event_id, so the server ignores a repeat.

  WIRING for SENSORS_FITTED 1 (3.3 V logic: never feed 5 V into an ESP32 pin)
    Pressure transducer, 0.5-4.5 V out -> 10k / 20k divider -> GPIO34
    Flow sensor YF-S201, pulse out      -> 10k / 20k divider -> GPIO27
  Use ADC1 pins only (32 to 39): ADC2 does not work while Wi-Fi is on.
*/

#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>

// ---------------------------------------------------------------- configuration
#ifndef SENSORS_FITTED
#define SENSORS_FITTED 0   // 1 once a pressure transducer and a flow sensor are wired
#endif

const char* WIFI_SSID     = "";                                         // empty: USB uplink only
const char* WIFI_PASSWORD = "";
const char* SERVER_URL    = "http://192.168.1.10:8000/api/telemetry";   // the laptop running start.bat
const char* DEVICE_KEY    = "demo-device-key";                          // X-Device-Key header
const char* DEVICE_ID     = "HW-NODE-01";                               // the registered bench node

const uint32_t REPORT_INTERVAL_MS = 2000;
const long     GMT_OFFSET_S       = 19800;   // IST = UTC + 05:30

const int PIN_BUTTON   = 0;    // BOOT button on most ESP32 dev boards (GPIO9 on ESP32-C3 boards)
const int PIN_LED      = 2;    // on-board LED on most dev boards; -1 if yours has none
const int PIN_PRESSURE = 34;
const int PIN_FLOW     = 27;

const float DIVIDER_GAIN          = 1.5f;    // 10k over 20k: the ADC sees two thirds of the sensor's volts
const float PRESSURE_MAX_BAR      = 12.0f;   // 0-1.2 MPa transducer
const float FLOW_PULSES_PER_LITRE = 450.0f;  // YF-S201 nominal; calibrate with a measured bucket

// ------------------------------------------------------------------------ state
enum TapState { TAP_OPEN, TAP_PINCHED, TAP_CLOSED };
const char* STATE_NAME[] = { "open", "pinched", "closed" };
const float STATE_BAR[]  = { 1.15f, 0.28f, 0.02f };   // what a tap on a healthy lane reads in each state
const float STATE_LPM[]  = { 6.0f, 1.6f, 0.0f };

TapState tapState = TAP_OPEN;
float emuBar = STATE_BAR[TAP_OPEN], emuLpm = STATE_LPM[TAP_OPEN];

const int QUEUE_SIZE = 60;                   // two minutes of readings
String queueBuf[QUEUE_SIZE];
int queueHead = 0, queueCount = 0;

volatile uint32_t flowPulses = 0;
uint32_t bootId = 0, sequence = 0;
uint32_t lastReport = 0, nextSendAt = 0, backoffMs = 1000, lastPress = 0;
bool buttonWasDown = false;

void IRAM_ATTR onFlowPulse() { flowPulses++; }

bool wifiConfigured() { return WIFI_SSID[0] != '\0'; }

// ---------------------------------------------------------------------- sensors
float readVolts(int pin) {
  uint32_t mv = 0;                                             // 16 samples tame the ADC's noise
  for (int i = 0; i < 16; i++) { mv += analogReadMilliVolts(pin); delay(2); }
  return (mv / 16.0f) / 1000.0f;
}

float pressureBar() {
#if SENSORS_FITTED
  float v = readVolts(PIN_PRESSURE) * DIVIDER_GAIN;            // 0.5 V = 0 bar, 4.5 V = full scale
  float bar = (v - 0.5f) / 4.0f * PRESSURE_MAX_BAR;
  return bar < 0 ? 0 : bar;
#else
  emuBar += (STATE_BAR[tapState] - emuBar) * 0.6f;             // ease towards the state's value, as a real line would
  float bar = emuBar + (random(-100, 101) / 100.0f) * 0.012f;  // and wobble like a real sensor
  return bar < 0 ? 0 : bar;
#endif
}

float flowLpm(float seconds) {
#if SENSORS_FITTED
  noInterrupts();
  uint32_t pulses = flowPulses;
  flowPulses = 0;
  interrupts();
  return (pulses / FLOW_PULSES_PER_LITRE) / seconds * 60.0f;
#else
  (void)seconds;
  emuLpm += (STATE_LPM[tapState] - emuLpm) * 0.6f;
  float lpm = emuLpm * (1.0f + (random(-100, 101) / 100.0f) * 0.03f);
  return lpm < 0.05f ? 0 : lpm;
#endif
}

// ----------------------------------------------------------------- button + LED
void pollButton() {
  bool down = digitalRead(PIN_BUTTON) == LOW;
  uint32_t now = millis();
  if (down && !buttonWasDown && now - lastPress > 250) {       // one step per press, debounced
    lastPress = now;
    tapState = (TapState)((tapState + 1) % 3);
    Serial.printf("tap is now %s\n", STATE_NAME[tapState]);
  }
  buttonWasDown = down;
  if (Serial.available()) {                                    // or type o / p / c in the serial monitor
    char ch = Serial.read();
    if (ch == 'o') tapState = TAP_OPEN;
    if (ch == 'p') tapState = TAP_PINCHED;
    if (ch == 'c') tapState = TAP_CLOSED;
  }
  if (PIN_LED >= 0) {
    bool on = tapState == TAP_CLOSED || (tapState == TAP_PINCHED && (now / 250) % 2 == 0);
    digitalWrite(PIN_LED, on ? HIGH : LOW);
  }
}

// ----------------------------------------------------------------------- uplink
String isoNow() {
  struct tm t;
  if (!getLocalTime(&t, 20)) return String("");                // clock not set yet
  char buf[32];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S+05:30", &t);
  return String(buf);
}

void enqueue(const String& payload) {
  if (queueCount == QUEUE_SIZE) {                              // full: the oldest reading goes
    queueHead = (queueHead + 1) % QUEUE_SIZE;
    queueCount--;
  }
  queueBuf[(queueHead + queueCount) % QUEUE_SIZE] = payload;
  queueCount++;
}

void connectWifi() {
  if (!wifiConfigured() || WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 8000) delay(250);
  if (WiFi.status() == WL_CONNECTED) Serial.printf("Wi-Fi connected, RSSI %d dBm\n", WiFi.RSSI());
}

bool postJson(const String& payload) {
  if (WiFi.status() != WL_CONNECTED) return false;
  HTTPClient http;
  http.setTimeout(4000);
  if (!http.begin(SERVER_URL)) return false;
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Key", DEVICE_KEY);
  int code = http.POST(payload);
  http.end();
  // 201 stored, 200 already stored. 422 means the payload is wrong: sending it again will not help.
  return code == 201 || code == 200 || code == 422;
}

// ------------------------------------------------------------------------ setup
void setup() {
  Serial.begin(115200);
  bootId = esp_random() % 1000000;                             // keeps event ids unique across restarts
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  if (PIN_LED >= 0) pinMode(PIN_LED, OUTPUT);
#if SENSORS_FITTED
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);                              // full 0-3.3 V input range
  pinMode(PIN_FLOW, INPUT);
  attachInterrupt(digitalPinToInterrupt(PIN_FLOW), onFlowPulse, RISING);
#endif
  connectWifi();
  if (wifiConfigured()) configTime(GMT_OFFSET_S, 0, "pool.ntp.org", "time.google.com");
  Serial.printf("JalSakhi tap node %s, sensors %s, uplink %s\n", DEVICE_ID,
                SENSORS_FITTED ? "fitted" : "emulated (press BOOT to change the tap)", wifiConfigured() ? "Wi-Fi + USB" : "USB");
  lastReport = millis();
}

// ------------------------------------------------------------------------- loop
void loop() {
  pollButton();
  uint32_t now = millis();

  if (now - lastReport >= REPORT_INTERVAL_MS) {
    float seconds = (now - lastReport) / 1000.0f;
    lastReport = now;
    sequence++;
    float bar = pressureBar(), lpm = flowLpm(seconds);
    const char* quality = SENSORS_FITTED ? "good" : "emulated";

    // USB uplink: one line the bridge on the laptop turns into a telemetry event (it adds the time)
    Serial.printf("JS1 {\"boot\":%lu,\"seq\":%lu,\"metrics\":{\"pressure_bar\":%.3f,\"flow_lpm\":%.2f},\"quality\":\"%s\"}\n",
                  (unsigned long)bootId, (unsigned long)sequence, bar, lpm, quality);

    String ts = isoNow();
    if (wifiConfigured() && ts.length() > 0) {                 // Wi-Fi uplink: never without a real timestamp
      char payload[320];
      snprintf(payload, sizeof(payload),
        "{\"event_id\":\"%s-%lu-%lu\",\"device_id\":\"%s\",\"ts\":\"%s\","
        "\"metrics\":{\"pressure_bar\":%.3f,\"flow_lpm\":%.2f},\"source\":\"hardware\",\"quality\":\"%s\"}",
        DEVICE_ID, (unsigned long)bootId, (unsigned long)sequence, DEVICE_ID, ts.c_str(), bar, lpm, quality);
      enqueue(String(payload));
    }
  }

  // Drain the buffer, oldest first. On failure wait, doubling the delay up to one minute.
  if (queueCount > 0 && now >= nextSendAt) {
    connectWifi();
    if (postJson(queueBuf[queueHead])) {
      queueBuf[queueHead] = "";
      queueHead = (queueHead + 1) % QUEUE_SIZE;
      queueCount--;
      backoffMs = 1000;
      nextSendAt = now;
    } else {
      nextSendAt = now + backoffMs;
      backoffMs = min<uint32_t>(backoffMs * 2, 60000);
    }
  }
  delay(10);
}
