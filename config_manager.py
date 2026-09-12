from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


APP_DIR = Path(os.getenv("APPDATA", Path.home())) / "AIQuotaWidget"
CONFIG_PATH = APP_DIR / "config.json"


@dataclass
class AntigravityConfig:
    enabled: bool = False
    endpoint_url: str = ""
    session_token: str = ""
    cookies: str = ""
    refresh_interval_sec: int = 600


@dataclass
class GitHubCopilotConfig:
    enabled: bool = False
    github_token: str = ""
    refresh_interval_sec: int = 300
    endpoint_url: str = "https://api.github.com/copilot_internal/v2/token"
    editor_version: str = "vscode/1.99.0"


@dataclass
class AppConfig:
    theme: str = "dark"
    accent_color: str = "#7C3AED"
    text_color: str = "#F9FAFB"
    background_color: str = "#111827"
    window_alpha: float = 0.94
    always_on_top: bool = True
    window_x: int | None = None
    window_y: int | None = None
    weekly_reset_weekday: int = 0
    weekly_reset_hour: int = 0
    weekly_reset_minute: int = 0
    weekly_reset_timezone: str = "local"
    rolling_reset_at: float | None = None
    weekly_reset_override: float | None = None
    ui_mode: str = "docked"
    antigravity: AntigravityConfig = field(default_factory=AntigravityConfig)
    github_copilot: GitHubCopilotConfig = field(default_factory=GitHubCopilotConfig)


class ConfigManager:
    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self.path = path

    def load(self) -> AppConfig:
        values: dict[str, Any] = {}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    values = loaded
            except (OSError, json.JSONDecodeError):
                pass
        config = AppConfig()
        self._apply_values(config, values)
        self._migrate_legacy(config, values)
        self._normalize(config)
        return config

    def save(self, config: AppConfig) -> None:
        self._normalize(config)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(config), indent=2, ensure_ascii=True)
        fd, temporary = tempfile.mkstemp(prefix="config-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _apply_values(config: AppConfig, values: dict[str, Any]) -> None:
        scalar_fields = {
            "theme", "accent_color", "text_color", "background_color", "window_alpha",
            "always_on_top", "window_x", "window_y", "weekly_reset_weekday",
            "weekly_reset_hour", "weekly_reset_minute", "weekly_reset_timezone",
            "rolling_reset_at", "weekly_reset_override", "ui_mode",
        }
        for key in scalar_fields:
            if key in values:
                setattr(config, key, values[key])
        for key, target in (("antigravity", config.antigravity), ("github_copilot", config.github_copilot)):
            nested = values.get(key)
            if isinstance(nested, dict):
                for field_name in asdict(target):
                    if field_name in nested:
                        setattr(target, field_name, nested[field_name])

    @staticmethod
    def _migrate_legacy(config: AppConfig, values: dict[str, Any]) -> None:
        if not isinstance(values.get("antigravity"), dict):
            config.antigravity.enabled = bool(
                values.get("quota_endpoint") or values.get("session_token") or values.get("bearer_token")
            )
            config.antigravity.endpoint_url = str(values.get("quota_endpoint", "") or "")
            config.antigravity.session_token = str(
                values.get("session_token") or values.get("bearer_token") or ""
            )
            config.antigravity.cookies = str(values.get("cookies", "") or "")
            config.antigravity.refresh_interval_sec = int(values.get("poll_interval_seconds", 600) or 600)

    @staticmethod
    def _normalize(config: AppConfig) -> None:
        config.theme = config.theme if config.theme in {"dark", "light", "system"} else "dark"
        config.window_alpha = min(1.0, max(0.55, float(config.window_alpha)))
        config.weekly_reset_weekday = min(6, max(0, int(config.weekly_reset_weekday)))
        config.weekly_reset_hour = min(23, max(0, int(config.weekly_reset_hour)))
        config.weekly_reset_minute = min(59, max(0, int(config.weekly_reset_minute)))
        config.always_on_top = bool(config.always_on_top)
        config.ui_mode = config.ui_mode if config.ui_mode in {"docked", "floating"} else "docked"
        config.antigravity.enabled = bool(config.antigravity.enabled)
        config.antigravity.refresh_interval_sec = min(3600, max(60, int(config.antigravity.refresh_interval_sec)))
        config.github_copilot.enabled = bool(config.github_copilot.enabled)
        config.github_copilot.refresh_interval_sec = min(3600, max(60, int(config.github_copilot.refresh_interval_sec)))
