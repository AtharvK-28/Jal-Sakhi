"""Forward the ESP32 tap node's readings from its USB cable to the JalSakhi server.

    python firmware/usb_bridge.py                 finds the board's serial port by itself
    python firmware/usb_bridge.py --port COM4

For when the board cannot reach the laptop over Wi-Fi (venue networks often isolate devices). The
firmware prints every reading as a line starting "JS1 "; this script reads those lines, adds the
time, and posts them to /api/telemetry. Close the Arduino serial monitor first: only one program
can hold the port.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

from jalsakhi_link import KEY, SERVER, post

USB_SERIAL_CHIPS = ("CP210", "CH340", "CH910", "FTDI", "USB SERIAL", "USB-SERIAL", "USB JTAG", "SILICON LABS")


def serial_module():
    try:
        import serial
        import serial.tools.list_ports
    except ImportError:
        print("Installing pyserial (needed once to read the USB port)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "pyserial"])
        import serial
        import serial.tools.list_ports
    return serial


def find_port(serial) -> str | None:
    ports = list(serial.tools.list_ports.comports())
    likely = [p for p in ports if any(chip in f"{p.description} {p.manufacturer or ''}".upper() for chip in USB_SERIAL_CHIPS)]
    for p in ports:
        print(f"  {p.device}: {p.description}")
    pick = likely or ports
    return pick[0].device if len(pick) == 1 else None


def main():
    ap = argparse.ArgumentParser(description="USB uplink for the JalSakhi tap node")
    ap.add_argument("--port", help="serial port of the board, e.g. COM4 or /dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--server", default=SERVER)
    ap.add_argument("--key", default=KEY)
    args = ap.parse_args()

    serial = serial_module()
    port = args.port or find_port(serial)
    if not port:
        sys.exit("Could not tell which port is the board. Unplug other USB serial devices, or pass --port.")
    print(f"Reading {port} at {args.baud} baud, forwarding to {args.server}. Ctrl+C to stop.")
    sent = 0
    while True:
        try:
            with serial.Serial(port, args.baud, timeout=2) as link:
                while True:
                    line = link.readline().decode(errors="replace").strip()
                    if not line.startswith("JS1 "):
                        if line:
                            print(f"\n  board: {line}")
                        continue
                    try:
                        r = json.loads(line[4:])
                        metrics, boot, seq = r["metrics"], r["boot"], r["seq"]
                    except (ValueError, KeyError):
                        continue  # a line cut off mid-way while the board was starting
                    result = post(args.server, args.key, f"HW-NODE-01-{boot}-{seq}", metrics, r.get("quality", "good"))
                    sent += result == "stored"
                    print(f"\r  {metrics.get('pressure_bar', 0):.2f} bar  {metrics.get('flow_lpm', 0):.1f} L/min   {result:<40} ({sent} stored)", end="", flush=True)
        except KeyboardInterrupt:
            print()
            return
        except Exception as exc:  # the cable was pulled, or another program took the port: keep trying
            print(f"\n  port problem ({exc}); retrying in 2 s")
            time.sleep(2)


if __name__ == "__main__":
    main()
