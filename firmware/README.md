# JalSakhi tap node

An ESP32 that stands in for one household tap in the network twin. While it reports, its pressure
and flow replace the simulated readings for one metered home (HH-011 by default; change it on the
**Devices & hardware** page), so the estimator, the fault detectors, the alerts and the household's
phone notification all react to the board on the table.

**Status.** `jalsakhi_node/jalsakhi_node.ino` compiles with the ESP32 Arduino core 3.3.11 for
"ESP32 Dev Module" and "ESP32C3 Dev Module", with and without `SENSORS_FITTED`. It has not been
flashed or run on a board from this repository; the first run on your board is the first real test.

## No sensors? The board plays a tap

With `SENSORS_FITTED 0` (the default) the board needs nothing attached. Each press of the **BOOT**
button moves to the next state:

| State | Reads | LED | What the system does |
|---|---|---|---|
| tap open | 1.15 bar, 6 L/min | off | home shown as receiving water |
| pipe pinched | 0.28 bar, 1.6 L/min | blinking | home turns amber; after 4 readings a "low pressure at this home only" alert |
| tap closed | 0.02 bar, 0 L/min | on | home turns red; "tap not delivering while the lane is" alert; the household is notified |

The values are generated on the board and sent marked `emulated`, and the dashboard says so. What is
real is the board, the firmware, the link, the ingestion and everything downstream.

## Three ways to connect

1. **USB cable (safest at a venue).** Flash the sketch as it is. Close the serial monitor, then:
   ```
   python firmware/usb_bridge.py
   ```
   It finds the board's serial port, reads the `JS1 ...` lines the firmware prints and posts them.
   `pyserial` is installed on first use. Pass `--port COM4` if it cannot tell which port is the board.
2. **Wi-Fi.** In the sketch set `WIFI_SSID`, `WIFI_PASSWORD` and `SERVER_URL` (the laptop's LAN
   address is shown in Demo controls and printed by `start.bat`), then flash. The board needs to
   reach the laptop; many public networks do not allow that.
3. **No board.** `python firmware/bench_node.py` plays the board from the laptop: press `o`, `p`
   or `c` to open, pinch or close the tap. Same endpoint, same effect.

Flash from the Arduino IDE (board "ESP32 Dev Module", no extra libraries), or from a terminal:

```
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/jalsakhi_node
arduino-cli upload  --fqbn esp32:esp32:esp32 -p COM4 firmware/jalsakhi_node
```

## When the sensors arrive

Set `SENSORS_FITTED 1` and wire them (3.3 V logic: never feed 5 V into an ESP32 pin):

| Sensor | Signal | ESP32 pin | Note |
|---|---|---|---|
| Pressure transducer, 0.5 to 4.5 V | analog | GPIO34 | through a 10k / 20k divider |
| Flow sensor YF-S201 | pulses | GPIO27 | through a 10k / 20k divider (5 V output) |

Use ADC1 pins only (32 to 39): ADC2 does not work while Wi-Fi is on. Calibrate both sensors against
a reference (a gauge, a measured bucket) before trusting a number.

## What the firmware does about bad connectivity

- Wi-Fi readings carry an NTP timestamp; none is sent until the clock is set.
- Unsent readings wait in a 60-slot ring buffer (oldest dropped first) and are re-sent with backoff.
- Every reading has a unique `event_id`; the server ignores a repeat, so re-sending is safe.
- The board is treated as silent after 12 s without a reading, and the simulator takes the tap back.

## The ingest contract

```
POST /api/telemetry        X-Device-Key: demo-device-key
{"event_id": "HW-NODE-01-123-7", "device_id": "HW-NODE-01", "ts": "2026-10-05T06:10:00+05:30",
 "metrics": {"pressure_bar": 1.12, "flow_lpm": 6.1}, "source": "hardware", "quality": "emulated"}
```

`201` stored, `200` already stored, `422` failed validation, `401` wrong or missing device key.

## Not done yet (field build)

Deep sleep between reports, buffer persistence across power loss, GSM / LoRa uplink, per-device
keys with signatures, over-the-air update, enclosure and surge protection.
