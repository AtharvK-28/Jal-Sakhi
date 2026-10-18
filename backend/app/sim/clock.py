"""Simulation clock: one-minute steps inside supply windows, coarse steps outside."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from .. import config as C


class SimClock:
    def __init__(self, start: datetime = C.SIM_START):
        self.now = start
        self._prev_win = None
        self._prev_day = start.date()
        self.win_idx, self.min_in_win = C.window_at(start.hour * 60 + start.minute)
        self.dt = 1

    def advance(self, max_dt: int | None = None, idle_dt: int | None = None) -> SimpleNamespace:
        w, _ = C.window_at(self.now.hour * 60 + self.now.minute)
        if w is not None:
            dt = 1
        else:
            gap = int((C.next_window_start(self.now) - self.now).total_seconds() // 60)
            dt = max(1, min(idle_dt or C.IDLE_DT_MIN, gap))
        if max_dt:
            dt = min(dt, max_dt)
        self.now += timedelta(minutes=dt)
        w, m = C.window_at(self.now.hour * 60 + self.now.minute)
        closed_idx = self._prev_win if (w is None and self._prev_win is not None) else None
        clk = SimpleNamespace(
            now=self.now, dt=dt, win_idx=w, min_in_win=m,
            new_window=w is not None and w != self._prev_win,
            new_day=self.now.date() != self._prev_day,
            closed_idx=closed_idx,
        )
        self._prev_win, self._prev_day = w, self.now.date()
        self.win_idx, self.min_in_win, self.dt = w, m, dt
        return clk

    @property
    def in_window(self) -> bool:
        return self.win_idx is not None

    def describe(self) -> dict:
        nxt = C.next_window_start(self.now)
        out = {"iso": self.now.isoformat(), "time": self.now.strftime("%H:%M"), "date": self.now.strftime("%d %b %Y"),
               "day": self.now.strftime("%A"), "in_window": self.in_window, "window_idx": self.win_idx,
               "min_in_window": int(self.min_in_win), "dt": self.dt,
               "next_window": nxt.strftime("%H:%M"), "mins_to_next": int((nxt - self.now).total_seconds() // 60)}
        if self.in_window:
            start, end, label = C.SUPPLY_WINDOWS[self.win_idx]
            out.update(window_label=label, window_start=f"{start // 60:02d}:{start % 60:02d}",
                       window_end=f"{end // 60:02d}:{end % 60:02d}", window_len=end - start)
        return out
