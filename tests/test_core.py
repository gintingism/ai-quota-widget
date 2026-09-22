from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parents[1]))

from config_manager import AppConfig, ConfigManager  # noqa: E402
from quota_fetcher import QuotaFetcher  # noqa: E402
from timer_engine import ROLLING_SECONDS, TimerEngine  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_invalid_numeric_values_use_safe_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({
                "window_alpha": "broken",
                "weekly_reset_hour": {},
                "github_copilot": {"refresh_interval_sec": "broken"},
            }), encoding="utf-8")
            config = ConfigManager(path).load()
        self.assertEqual(config.window_alpha, 0.94)
        self.assertEqual(config.weekly_reset_hour, 0)
        self.assertEqual(config.github_copilot.refresh_interval_sec, 300)


class TimerTests(unittest.TestCase):
    def test_epoch_zero_is_respected(self) -> None:
        engine = TimerEngine(None, None, 0, 0, 0)
        engine.trigger_session(now=0)
        self.assertEqual(engine.rolling_reset_at, ROLLING_SECONDS)


class FetcherTests(unittest.TestCase):
    def test_copilot_404_falls_back_to_identity(self) -> None:
        config = AppConfig()
        config.github_copilot.enabled = True
        config.github_copilot.github_token = "test-token"
        fetcher = QuotaFetcher(config, Mock())
        response = Mock(status_code=404, headers={})
        response.json.return_value = {"login": "test-user"}
        response.raise_for_status.return_value = None
        fetcher._request = Mock(return_value=response)
        snapshot = fetcher._fetch_github_copilot()
        self.assertEqual(snapshot.source, "remote")
        self.assertIsNone(snapshot.error)
        self.assertIn("test-user", snapshot.account_status)


if __name__ == "__main__":
    unittest.main()
