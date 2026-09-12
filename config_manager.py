from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


APP_DIR = Path(os.getenv("APPDATA", Path.home())) / "AIQuotaWidget"
CONFIG_PATH = APP_DIR / "config.json"


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
    quota_endpoint: str = ""
    bearer_token: str = ""
    session_token: str = ""
    cookies: str = ""
    poll_interval_seconds: int = 600


class ConfigManager:
    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self.path = path

    def load(self) -> AppConfig:
        config = AppConfig()
        if self.path.exists():
            try:
                values = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(values, dict):
                    for key in asdict(config):
                        if key in values:
                            setattr(config, key, values[key])
            except (OSError, json.JSONDecodeError):
                pass
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
    def _normalize(config: AppConfig) -> None:
        config.theme = config.theme if config.theme in {"dark", "light", "system"} else "dark"
        config.window_alpha = min(1.0, max(0.55, float(config.window_alpha)))
        config.weekly_reset_weekday = min(6, max(0, int(config.weekly_reset_weekday)))
        config.weekly_reset_hour = min(23, max(0, int(config.weekly_reset_hour)))
        config.weekly_reset_minute = min(59, max(0, int(config.weekly_reset_minute)))
        config.always_on_top = bool(config.always_on_top)
        config.ui_mode = config.ui_mode if config.ui_mode in {"docked", "floating"} else "docked"
        config.poll_interval_seconds = min(3600, max(60, int(config.poll_interval_seconds)))
