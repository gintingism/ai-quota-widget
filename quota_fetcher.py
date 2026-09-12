from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from config_manager import AppConfig, AntigravityConfig, GitHubCopilotConfig


@dataclass(frozen=True)
class QuotaModel:
    name: str
    remaining_percent: float | None = None
    reset_at: float | None = None


@dataclass(frozen=True)
class ProviderSnapshot:
    provider: str
    models: tuple[QuotaModel, ...] = ()
    quota_percent: float | None = None
    reset_at: float | None = None
    rolling_reset_at: float | None = None
    weekly_reset_at: float | None = None
    plan_tier: str = "Unknown"
    account_status: str = "Not connected"
    fetched_at: float = 0.0
    source: str = "local"
    error: str | None = None


@dataclass(frozen=True)
class AggregatedQuotaState:
    providers: dict[str, ProviderSnapshot] = field(default_factory=dict)
    fetched_at: float = 0.0


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
        used = _first(value, "used", "consumed")
        limit = _first(value, "limit", "total", "allowed")
        if used is not None and limit is not None:
            try:
                return max(0.0, min(100.0, 100.0 * (1 - float(used) / float(limit))))
            except (TypeError, ValueError, ZeroDivisionError):
                return None
        value = _first(value, "remainingPercent", "remaining_percentage", "percent",
                        "percentage", "remaining", "remainingQuota")
    try:
        number = float(value)
        return max(0.0, min(100.0, number))
    except (TypeError, ValueError):
        return None


def _cookies(value: str) -> dict[str, str]:
    return {
        part.split("=", 1)[0].strip(): part.split("=", 1)[1].strip()
        for part in value.split(";") if "=" in part
    }


class QuotaFetcher:
    """Fetches both providers concurrently and emits immutable aggregated state."""

    def __init__(self, config: AppConfig, on_result: Callable[[AggregatedQuotaState], None]) -> None:
        self.config = config
        self.on_result = on_result
        self._stop = threading.Event()
        self._refresh_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._state: dict[str, ProviderSnapshot] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="quota-fetcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def refresh_now(self) -> None:
        threading.Thread(target=self._fetch_all, name="quota-refresh", daemon=True).start()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._fetch_all()
            intervals = [
                provider.refresh_interval_sec
                for provider, enabled in (
                    (self.config.antigravity, self.config.antigravity.enabled),
                    (self.config.github_copilot, self.config.github_copilot.enabled),
                ) if enabled
            ]
            self._stop.wait(min(intervals or [600]))

    def _fetch_all(self) -> None:
        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="quota-provider") as pool:
                futures = {}
                if self.config.antigravity.enabled:
                    futures["antigravity"] = pool.submit(self._fetch_antigravity)
                if self.config.github_copilot.enabled:
                    futures["github_copilot"] = pool.submit(self._fetch_github_copilot)
                for provider, future in futures.items():
                    try:
                        snapshot = future.result()
                    except Exception as exc:
                        snapshot = ProviderSnapshot(provider, error=f"Fetcher error: {str(exc)[:120]}")
                    with self._state_lock:
                        self._state[provider] = snapshot
            with self._state_lock:
                state = AggregatedQuotaState(dict(self._state), time.time())
            self.on_result(state)
        finally:
            self._refresh_lock.release()

    def _request(self, url: str, headers: dict[str, str], cookies: dict[str, str] | None = None) -> requests.Response:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Endpoint URL tidak valid")
        return requests.get(url, headers=headers, cookies=cookies or {}, timeout=15)

    def _fetch_antigravity(self) -> ProviderSnapshot:
        provider = self.config.antigravity
        try:
            headers = {"Accept": "application/json", "User-Agent": "AIQuotaWidget/1.0"}
            if provider.session_token:
                headers["Authorization"] = f"Bearer {provider.session_token.removeprefix('Bearer ').strip()}"
            response = self._request(provider.endpoint_url, headers, _cookies(provider.cookies))
            if response.status_code == 401:
                return ProviderSnapshot("antigravity", error="401 Unauthorized: token kedaluwarsa")
            response.raise_for_status()
            return self._parse_antigravity(response.json())
        except (requests.RequestException, ValueError, json.JSONDecodeError, TypeError) as exc:
            return ProviderSnapshot("antigravity", error=str(exc)[:160])

    def _parse_antigravity(self, payload: Any) -> ProviderSnapshot:
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            raise ValueError("Response Antigravity harus berupa object JSON")
        raw_models = _first(data, "models", "quotas", "limits", "usage") or {}
        models: list[QuotaModel] = []
        entries = raw_models if isinstance(raw_models, list) else raw_models.items() if isinstance(raw_models, dict) else ()
        for name, item in entries if isinstance(raw_models, dict) else (
            (str(item.get("name", "Model")), item) for item in raw_models if isinstance(item, dict)
        ):
            percent = _percent(item)
            reset = _epoch(_first(item, "resetAt", "reset_at", "resetTime", "resetsAt")) if isinstance(item, dict) else None
            models.append(QuotaModel(str(name), percent, reset))
        return ProviderSnapshot(
            provider="antigravity",
            models=tuple(models),
            rolling_reset_at=_epoch(_first(data, "rollingResetAt", "rolling_reset_at", "fiveHourResetAt")),
            weekly_reset_at=_epoch(_first(data, "weeklyResetAt", "weekly_reset_at", "weeklyCycleResetAt")),
            account_status=str(_first(data, "accountStatus", "status", "account") or "Connected"),
            fetched_at=time.time(),
            source="remote",
        )

    def _fetch_github_copilot(self) -> ProviderSnapshot:
        provider = self.config.github_copilot
        try:
            token = provider.github_token.removeprefix("Bearer ").strip()
            if not token:
                return ProviderSnapshot("github_copilot", error="GitHub token belum dikonfigurasi")
            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "Editor-Version": provider.editor_version,
                "User-Agent": "AIQuotaWidget/1.0",
            }
            response = self._request(provider.endpoint_url, headers)
            if response.status_code == 401:
                return ProviderSnapshot("github_copilot", error="401 Unauthorized: GitHub token invalid")
            if response.status_code == 429:
                reset = _epoch(response.headers.get("X-RateLimit-Reset"))
                return ProviderSnapshot("github_copilot", reset_at=reset, error="GitHub API rate limit")
            response.raise_for_status()
            return self._parse_copilot(response.json(), response.headers)
        except (requests.RequestException, ValueError, json.JSONDecodeError, TypeError) as exc:
            return ProviderSnapshot("github_copilot", error=str(exc)[:160])

    def _parse_copilot(self, payload: Any, headers: dict[str, str]) -> ProviderSnapshot:
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            raise ValueError("Response GitHub Copilot harus berupa object JSON")
        quota = _percent(_first(data, "quota", "usage", "monthlyQuota", "completions"))
        remaining = _percent(_first(data, "remainingPercent", "quotaRemainingPercent"))
        reset = _epoch(_first(data, "resetAt", "reset_at", "quotaResetAt", "resetDate"))
        if reset is None:
            reset = _epoch(headers.get("X-RateLimit-Reset"))
        if remaining is None and quota is not None:
            remaining = quota
        return ProviderSnapshot(
            provider="github_copilot",
            quota_percent=remaining,
            reset_at=reset,
            plan_tier=str(_first(data, "plan", "planTier", "tier", "sku") or "Copilot"),
            account_status=str(_first(data, "status", "accountStatus") or "Connected"),
            fetched_at=time.time(),
            source="remote",
        )
