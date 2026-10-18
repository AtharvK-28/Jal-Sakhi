"""Stands in for the ESP32 tap node when there is no board to hand.

    python firmware/bench_node.py                 press o / p / c to open, pinch or close the tap, q to quit
    python firmware/bench_node.py --state closed --seconds 30

It posts the same readings to the same endpoint as the firmware in jalsakhi_node/, marked "emulated",
so the twin, the detectors and the alerts can be shown end to end without hardware.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time

from jalsakhi_link import KEY, SERVER, STATES, post

KEYS = {"o": "open", "p": "pinched", "c": "closed"}


def pressed() -> str | None:
    """A key the user has pressed since last asked, without waiting for one."""
    if os.name == "nt":
        import msvcrt
        return msvcrt.getwch().lower() if msvcrt.kbhit() else None
    import select
    if select.select([sys.stdin], [], [], 0)[0]:  # on Linux / macOS a key counts once Enter is pressed
        return sys.stdin.readline().strip().lower()[:1] or None
    return None


def main():
    ap = argparse.ArgumentParser(description="Play the JalSakhi tap node from this computer")
    ap.add_argument("--server", default=SERVER)
    ap.add_argument("--key", default=KEY)
    ap.add_argument("--state", choices=list(STATES), default="open")
    ap.add_argument("--interval", type=float, default=2.0, help="seconds between readings")
    ap.add_argument("--seconds", type=float, default=0, help="stop after this long (0: run until q)")
    args = ap.parse_args()

    state, bar, lpm = args.state, *STATES[args.state]
    boot, seq, started = random.randrange(1_000_000), 0, time.time()
    print(f"Tap node stand-in -> {args.server}   [o] open  [p] pinch  [c] close  [q] quit")
    while not args.seconds or time.time() - started < args.seconds:
        until = time.time() + args.interval
        while time.time() < until:
            k = pressed()
            if k == "q":
                return
            if k in KEYS:
                state = KEYS[k]
            time.sleep(0.05)
        seq += 1
        bar += (STATES[state][0] - bar) * 0.6  # ease towards the state's value, as the firmware does
        lpm += (STATES[state][1] - lpm) * 0.6
        reading = {"pressure_bar": round(max(0.0, bar + random.uniform(-0.012, 0.012)), 3),
                   "flow_lpm": round(max(0.0, lpm * (1 + random.uniform(-0.03, 0.03))), 2)}
        result = post(args.server, args.key, f"HW-NODE-01-sim{boot}-{seq}", reading, quality="emulated")
        print(f"\r  tap {state:<8} {reading['pressure_bar']:.2f} bar  {reading['flow_lpm']:.1f} L/min   {result:<40}", end="", flush=True)
    print()


if __name__ == "__main__":
    main()
