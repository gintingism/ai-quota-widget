from __future__ import annotations

import time
from datetime import datetime, timedelta
from dataclasses import dataclass


ROLLING_SECONDS = 5 * 60 * 60


@dataclass(frozen=True)
class TimerSnapshot:
    rolling_remaining: int
    weekly_remaining: int
    weekly_reset_at: datetime


class TimerEngine:
    def __init__(self, rolling_reset_at: float | None, weekly_override: float | None,
                 weekday: int, hour: int, minute: int) -> None:
        self.rolling_reset_at = rolling_reset_at
        self.weekly_override = weekly_override
        self.weekday = weekday
        self.hour = hour
        self.minute = minute

    def trigger_session(self, now: float | None = None) -> None:
        self.rolling_reset_at = (time.time() if now is None else now) + ROLLING_SECONDS

    def force_reset(self, now: float | None = None) -> None:
        self.rolling_reset_at = time.time() if now is None else now

    def snapshot(self, now: float | None = None) -> TimerSnapshot:
        current = time.time() if now is None else now
        rolling_remaining = max(0, int(self.rolling_reset_at - current)) if self.rolling_reset_at else 0
        weekly_at = self.next_weekly_reset(current)
        weekly_remaining = max(0, int(weekly_at.timestamp() - current))
        return TimerSnapshot(rolling_remaining, weekly_remaining, weekly_at)

    def next_weekly_reset(self, now: float | None = None) -> datetime:
        current = datetime.fromtimestamp(time.time() if now is None else now).astimezone()
        if self.weekly_override and self.weekly_override > current.timestamp():
            return datetime.fromtimestamp(self.weekly_override).astimezone()
        days_ahead = (self.weekday - current.weekday()) % 7
        candidate = current.replace(hour=self.hour, minute=self.minute, second=0, microsecond=0)
        if days_ahead or candidate <= current:
            candidate += timedelta(days=days_ahead or 7)
        return candidate
