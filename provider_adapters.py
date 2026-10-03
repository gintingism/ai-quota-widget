from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Protocol

from quota_models import ProviderSnapshot


class QuotaProvider(Protocol):
    name: str

    def fetch(self) -> ProviderSnapshot:
        ...


class AntigravityUsageReader:
    """Read the supported local CLI output without exposing credentials."""

    def __init__(self, cache_path: Path | None = None, timeout_sec: float = 8.0) -> None:
        self.cache_path = cache_path or (
            Path(os.getenv("LOCALAPPDATA", Path.home())) / "AIQuotaWidget" / "antigravity-usage.json"
        )
        self.timeout_sec = timeout_sec

    def read(self) -> tuple[Any, str]:
        try:
            completed = subprocess.run(
                ["antigravity", "/usage"],
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode == 0 and completed.stdout.strip():
                payload = json.loads(completed.stdout)
                self._write_cache(payload)
                return payload, "local"
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError, ValueError):
            pass
        cached = self._read_cache()
        if cached is not None:
            return cached, "cache"
        raise RuntimeError("Antigravity usage command unavailable")

    def _write_cache(self, payload: Any) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
        os.replace(temporary, self.cache_path)

    def _read_cache(self) -> Any | None:
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None


class AntigravityProvider:
    name = "antigravity"

    def __init__(self, parser: Any, reader: AntigravityUsageReader) -> None:
        self.parser = parser
        self.reader = reader

    def fetch(self) -> ProviderSnapshot:
        payload, source = self.reader.read()
        snapshot = self.parser(payload)
        return ProviderSnapshot(
            provider=snapshot.provider,
            models=snapshot.models,
            quota_percent=snapshot.quota_percent,
            reset_at=snapshot.reset_at,
            rolling_reset_at=snapshot.rolling_reset_at,
            weekly_reset_at=snapshot.weekly_reset_at,
            plan_tier=snapshot.plan_tier,
            account_status=snapshot.account_status,
            fetched_at=time.time(),
            source=source,
            error=snapshot.error,
        )
