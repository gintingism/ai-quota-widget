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

from config_manager import AppConfig

COPILOT_USER_ENDPOINT = "https://api.github.com/copilot_internal/user"


@dataclass(frozen=True)
class QuotaModel:
    name: str
    remaining_percent: float | None = None
    reset_at: float | None = None
    remaining: float | None = None
    entitlement: float | None = None
    unlimited: bool | None = None


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


def _remaining_percent(value: Any) -> float | None:
    if isinstance(value, dict):
        used = _first(value, "used", "consumed")
        limit = _first(value, "limit", "total", "allowed")
        if used is not None and limit is not None:
            try:
                return max(0.0, min(100.0, 100.0 * (1 - float(used) / float(limit))))
            except (TypeError, ValueError, ZeroDivisionError):
                return None
        nested = _first(value, "quota", "usage", "limit")
        if isinstance(nested, dict):
            nested_percent = _remaining_percent(nested)
            if nested_percent is not None:
                return nested_percent
        value = _first(
            value, "remainingPercent", "remaining_percentage", "percent",
            "percentage", "remaining", "remainingQuota",
        )
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _snapshot_percent(value: Any) -> float | None:
    """Read Copilot snapshot percentages without letting a zero count win."""
    if not isinstance(value, dict):
        return _remaining_percent(value)
    percent = _first(value, "percent_remaining", "percentRemaining")
    if percent is not None:
        return _remaining_percent(percent)
    return _remaining_percent(value)


def _parse_cookies(value: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in value.split(";"):
        if "=" in part:
            name, cookie_value = part.split("=", 1)
            cookies[name.strip()] = cookie_value.strip()
    return cookies


class QuotaFetcher:
    """Fetches providers off the Tk thread and emits immutable combined state."""

    def __init__(self, config: AppConfig, on_result: Callable[[AggregatedQuotaState], None]) -> None:
        self.config = config
        self.on_result = on_result
        self._stop = threading.Event()
        self._refresh_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state: dict[str, ProviderSnapshot] = {}
        self._next_due = {"antigravity": 0.0, "github_copilot": 0.0}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="quota-fetcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def refresh_now(self) -> None:
        threading.Thread(
            target=lambda: self._fetch_all(force=True),
            name="quota-refresh",
            daemon=True,
        ).start()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._fetch_all()
            now = time.monotonic()
            due = [deadline - now for deadline in self._next_due.values() if deadline > now]
            self._stop.wait(min(due or [1.0]))

    def _fetch_all(self, force: bool = False) -> None:
        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            now = time.monotonic()
            jobs: dict[str, Any] = {}
            if self.config.antigravity.enabled and (
                force or now >= self._next_due["antigravity"]
            ):
                jobs["antigravity"] = self._fetch_antigravity
            if self.config.github_copilot.enabled and (
                force or now >= self._next_due["github_copilot"]
            ):
                jobs["github_copilot"] = self._fetch_github_copilot

            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="quota-provider") as pool:
                futures = {name: pool.submit(job) for name, job in jobs.items()}
                for provider, future in futures.items():
                    try:
                        snapshot = future.result()
                    except Exception:
                        snapshot = ProviderSnapshot(
                            provider=provider,
                            error="Provider fetch failed",
                        )
                    with self._state_lock:
                        self._state[provider] = snapshot
                    interval = (
                        self.config.antigravity.refresh_interval_sec
                        if provider == "antigravity"
                        else self.config.github_copilot.refresh_interval_sec
                    )
                    self._next_due[provider] = time.monotonic() + interval

            with self._state_lock:
                state = AggregatedQuotaState(dict(self._state), time.time())
            try:
                self.on_result(state)
            except Exception:
                # A UI callback must not terminate the polling loop.
                pass
        finally:
            self._refresh_lock.release()

    @staticmethod
    def _request(
        url: str,
        headers: dict[str, str],
        cookies: dict[str, str] | None = None,
    ) -> requests.Response:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Endpoint URL tidak valid")
        return requests.get(url, headers=headers, cookies=cookies or {}, timeout=15)

    def _fetch_antigravity(self) -> ProviderSnapshot:
        provider = self.config.antigravity
        try:
            headers = {"Accept": "application/json", "User-Agent": "AIQuotaWidget/1.0"}
            if provider.session_token:
                token = provider.session_token.removeprefix("Bearer ").strip()
                headers["Authorization"] = "Bearer " + token
            response = self._request(provider.endpoint_url, headers, _parse_cookies(provider.cookies))
            if response.status_code == 401:
                return ProviderSnapshot("antigravity", error="401 Unauthorized: token expired")
            response.raise_for_status()
            return self._parse_antigravity(response.json())
        except (requests.RequestException, ValueError, json.JSONDecodeError, TypeError):
            return ProviderSnapshot("antigravity", error="Antigravity request failed")

    def _parse_antigravity(self, payload: Any) -> ProviderSnapshot:
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            raise ValueError("Antigravity response must be a JSON object")
        raw_models = _first(data, "models", "quotas", "limits", "usage") or {}
        if isinstance(raw_models, dict):
            entries = raw_models.items()
        elif isinstance(raw_models, list):
            entries = (
                (str(item.get("name", "Model")), item)
                for item in raw_models if isinstance(item, dict)
            )
        else:
            entries = ()
        models = []
        for name, item in entries:
            percent = _remaining_percent(item)
            reset = _epoch(_first(item, "resetAt", "reset_at", "resetTime", "resetsAt")) \
                if isinstance(item, dict) else None
            models.append(QuotaModel(str(name), percent, reset))
        return ProviderSnapshot(
            provider="antigravity",
            models=tuple(models),
            rolling_reset_at=_epoch(_first(
                data, "rollingResetAt", "rolling_reset_at", "fiveHourResetAt",
            )),
            weekly_reset_at=_epoch(_first(
                data, "weeklyResetAt", "weekly_reset_at", "weeklyCycleResetAt",
            )),
            account_status=str(_first(data, "accountStatus", "status", "account") or "Connected"),
            fetched_at=time.time(),
            source="remote",
        )

    def _fetch_github_copilot(self) -> ProviderSnapshot:
        provider = self.config.github_copilot
        token = provider.github_token.removeprefix("Bearer ").strip()
        if not token:
            return ProviderSnapshot("github_copilot", error="GitHub token not configured")
        headers = {
            "Accept": "application/json",
            "Authorization": "Bearer " + token,
            "Editor-Version": provider.editor_version,
            "User-Agent": "AIQuotaWidget/1.0",
        }
        try:
            response = self._request(provider.endpoint_url, headers)
            if response.status_code == 401:
                return ProviderSnapshot("github_copilot", error="401 Unauthorized: token invalid")
            if response.status_code == 429:
                return ProviderSnapshot(
                    "github_copilot",
                    reset_at=_epoch(response.headers.get("X-RateLimit-Reset")),
                    error="GitHub API rate limit",
                )
            if response.status_code == 404:
                return self._fetch_copilot_user(headers)
            response.raise_for_status()
            snapshot = self._parse_copilot(response.json(), response.headers)
            if snapshot.quota_percent is not None:
                return snapshot
            if provider.endpoint_url.rstrip("/") != COPILOT_USER_ENDPOINT:
                return self._fetch_copilot_user(headers)
            return self._fetch_copilot_identity(headers)
        except (requests.RequestException, ValueError, json.JSONDecodeError, TypeError):
            return ProviderSnapshot("github_copilot", error="GitHub Copilot request failed")

    def _fetch_copilot_user(self, headers: dict[str, str]) -> ProviderSnapshot:
        response = self._request(COPILOT_USER_ENDPOINT, headers)
        if response.status_code == 401:
            return ProviderSnapshot("github_copilot", error="401 Unauthorized: token invalid")
        if response.status_code == 404:
            return self._fetch_copilot_identity(headers)
        if response.status_code == 429:
            return ProviderSnapshot(
                "github_copilot",
                reset_at=_epoch(response.headers.get("X-RateLimit-Reset")),
                error="GitHub API rate limit",
            )
        response.raise_for_status()
        snapshot = self._parse_copilot(response.json(), response.headers)
        return snapshot if snapshot.quota_percent is not None else self._fetch_copilot_identity(headers)

    def _fetch_copilot_identity(self, headers: dict[str, str]) -> ProviderSnapshot:
        identity = self._request("https://api.github.com/user", headers)
        if identity.status_code == 401:
            return ProviderSnapshot("github_copilot", error="401 Unauthorized: token invalid")
        identity.raise_for_status()
        return self._parse_copilot_identity(identity.json())

    @staticmethod
    def _parse_copilot_identity(payload: Any) -> ProviderSnapshot:
        data = payload if isinstance(payload, dict) else {}
        login = str(_first(data, "login", "name") or "GitHub account")
        return ProviderSnapshot(
            provider="github_copilot",
            plan_tier="GitHub account",
            account_status=f"Connected as {login}; quota endpoint unavailable",
            fetched_at=time.time(),
            source="remote",
        )

    def _parse_copilot(self, payload: Any, headers: dict[str, str]) -> ProviderSnapshot:
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        if isinstance(data, dict) and isinstance(data.get("user"), dict):
            data = data["user"]
        if not isinstance(data, dict):
            raise ValueError("Copilot response must be a JSON object")
        snapshots = _first(data, "quota_snapshots", "quotaSnapshots")
        if isinstance(snapshots, (dict, list)):
            entries = (
                snapshots.items()
                if isinstance(snapshots, dict)
                else (
                    (str(item.get("name", "Model")), item)
                    for item in snapshots if isinstance(item, dict)
                )
            )
            models: list[QuotaModel] = []
            for name, item in entries:
                if not isinstance(item, dict):
                    continue
                models.append(QuotaModel(
                    name=str(name),
                    remaining_percent=_snapshot_percent(item),
                    reset_at=_epoch(_first(item, "quota_reset_at", "quotaResetAt")),
                    remaining=_number(_first(item, "remaining", "quota_remaining")),
                    entitlement=_number(item.get("entitlement")),
                    unlimited=item.get("unlimited") if isinstance(item.get("unlimited"), bool) else None,
                ))
            finite = [
                model for model in models
                if model.unlimited is not True and model.remaining_percent is not None
            ]
            premium = next(
                (model for model in finite if model.name.lower() == "premium_interactions"),
                None,
            )
            selected = premium or next(
                (model for model in finite if model.remaining_percent is not None),
                None,
            )
            if selected is None:
                selected = next(
                    (model for model in models if model.remaining_percent is not None),
                    None,
                )
            reset = _epoch(_first(
                data, "quota_reset_date_utc", "quotaResetDateUtc",
                "resetAt", "reset_at", "quotaResetAt", "resetDate",
            ))
            return ProviderSnapshot(
                provider="github_copilot",
                models=tuple(models),
                quota_percent=selected.remaining_percent if selected else None,
                reset_at=reset or (selected.reset_at if selected else None) \
                    or _epoch(headers.get("X-RateLimit-Reset")),
                plan_tier=str(_first(data, "copilot_plan", "plan", "planTier", "tier", "sku") or "Copilot"),
                account_status=str(_first(data, "status", "accountStatus") or "Connected"),
                fetched_at=time.time(),
                source="remote",
            )
        quota = _remaining_percent(_first(
            data, "quota", "usage", "monthlyQuota", "completions",
            "premiumInteractions", "premium_interactions",
        ))
        remaining = _remaining_percent(_first(
            data, "remainingPercent", "quotaRemainingPercent",
            "percentRemaining", "percent_remaining",
        ))
        breakdown = _first(data, "breakdown", "quotas", "limits")
        if remaining is None and isinstance(breakdown, dict):
            percentages = [
                _remaining_percent(item) for item in breakdown.values()
                if isinstance(item, (dict, int, float, str))
            ]
            percentages = [percent for percent in percentages if percent is not None]
            if percentages:
                remaining = min(percentages)
        reset = _epoch(_first(data, "resetAt", "reset_at", "quotaResetAt", "resetDate"))
        remaining = remaining if remaining is not None else quota
        return ProviderSnapshot(
            provider="github_copilot",
            quota_percent=remaining,
            reset_at=reset or _epoch(headers.get("X-RateLimit-Reset")),
            plan_tier=str(_first(data, "plan", "planTier", "tier", "sku") or "Copilot"),
            account_status=str(_first(data, "status", "accountStatus") or "Connected"),
            fetched_at=time.time(),
            source="remote",
        )
