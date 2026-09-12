from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from config_manager import AppConfig


@dataclass(frozen=True)
class QuotaModel:
    name: str
    remaining_percent: float | None = None
    reset_at: float | None = None


@dataclass(frozen=True)
class QuotaSnapshot:
    models: tuple[QuotaModel, ...]
    rolling_reset_at: float | None = None
    weekly_reset_at: float | None = None
    account_status: str = "Not connected"
    fetched_at: float = 0.0
    source: str = "local"
    error: str | None = None


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _epoch(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value / 1000 if value > 10_000_000_000 else value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            try:
                return parsedate_to_datetime(value).timestamp()
            except (TypeError, ValueError):
                return None
    return None


def _percent(value: Any) -> float | None:
    if isinstance(value, dict):
        value = _first(value, "remainingPercent", "remaining_percentage", "percent", "percentage", "remaining")
    try:
        number = float(value)
        return max(0.0, min(100.0, number if number <= 100 else 100))
    except (TypeError, ValueError):
        return None


class QuotaFetcher:
    """Polls a user-configured status endpoint; it does not discover credentials."""

    def __init__(self, config: AppConfig, on_result: Callable[[QuotaSnapshot], None]) -> None:
        self.config = config
        self.on_result = on_result
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="quota-fetcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def refresh_now(self) -> None:
        threading.Thread(target=self._fetch_once, name="quota-refresh", daemon=True).start()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._fetch_once()
            self._stop.wait(self.config.poll_interval_seconds)

    def _fetch_once(self) -> None:
        if not self.config.quota_endpoint:
            self.on_result(QuotaSnapshot((), source="local", error="Endpoint belum dikonfigurasi"))
            return
        try:
            parsed = urlparse(self.config.quota_endpoint)
            if parsed.scheme not in {"https", "http"} or not parsed.netloc:
                raise ValueError("URL endpoint tidak valid")
            headers = {"Accept": "application/json", "User-Agent": "AIQuotaWidget/1.0"}
            token = self.config.bearer_token or self.config.session_token
            if token:
                headers["Authorization"] = f"Bearer {token.removeprefix('Bearer ').strip()}"
            cookies = self._cookies()
            response = requests.get(self.config.quota_endpoint, headers=headers, cookies=cookies,
                                    timeout=15)
            response.raise_for_status()
            payload = response.json()
            self.on_result(self._parse(payload))
        except (requests.RequestException, ValueError, json.JSONDecodeError, TypeError) as exc:
            self.on_result(QuotaSnapshot((), source="local", error=str(exc)[:160]))

    def _cookies(self) -> dict[str, str]:
        if not self.config.cookies.strip():
            return {}
        return {part.split("=", 1)[0].strip(): part.split("=", 1)[1].strip()
                for part in self.config.cookies.split(";") if "=" in part}

    def _parse(self, payload: Any) -> QuotaSnapshot:
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            raise ValueError("Response quota harus berupa object JSON")
        raw_models = _first(data, "models", "quotas", "limits", "usage") or {}
        models: list[QuotaModel] = []
        if isinstance(raw_models, list):
            entries = ((str(item.get("name", "Model")), item) for item in raw_models if isinstance(item, dict))
        elif isinstance(raw_models, dict):
            entries = raw_models.items()
        else:
            entries = ()
        for name, item in entries:
            if isinstance(item, dict):
                percent = _percent(item)
                reset = _epoch(_first(item, "resetAt", "reset_at", "resetTime", "resetsAt"))
            else:
                percent, reset = _percent(item), None
            models.append(QuotaModel(str(name), percent, reset))
        return QuotaSnapshot(
            tuple(models),
            _epoch(_first(data, "rollingResetAt", "rolling_reset_at", "fiveHourResetAt", "resetAt")),
            _epoch(_first(data, "weeklyResetAt", "weekly_reset_at", "weeklyCycleResetAt")),
            str(_first(data, "accountStatus", "status", "account",) or "Connected"),
            time.time(), "remote",
        )
