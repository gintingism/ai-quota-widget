from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parents[1]))

from config_manager import AppConfig, ConfigManager  # noqa: E402
from quota_fetcher import COPILOT_USER_ENDPOINT, QuotaFetcher  # noqa: E402
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
        config.github_copilot.endpoint_url = "https://api.github.com/copilot_internal/v2/token"
        fetcher = QuotaFetcher(config, Mock())
        response = Mock(status_code=404, headers={})
        response.json.return_value = {"login": "test-user"}
        response.raise_for_status.return_value = None
        fetcher._request = Mock(return_value=response)
        snapshot = fetcher._fetch_github_copilot()
        self.assertEqual(snapshot.source, "remote")
        self.assertIsNone(snapshot.error)
        self.assertIn("test-user", snapshot.account_status)

    def test_copilot_token_endpoint_falls_back_to_quota_user_endpoint(self) -> None:
        config = AppConfig()
        config.github_copilot.enabled = True
        config.github_copilot.github_token = "test-token"
        config.github_copilot.endpoint_url = "https://api.github.com/copilot_internal/v2/token"
        fetcher = QuotaFetcher(config, Mock())
        token_response = Mock(status_code=200, headers={})
        token_response.json.return_value = {"token": "copilot-session-token"}
        quota_response = Mock(status_code=200, headers={})
        quota_response.json.return_value = {
            "breakdown": {"chat": {"quota": {"used": 25, "limit": 100}}},
            "plan": "individual",
        }
        fetcher._request = Mock(side_effect=[token_response, quota_response])
        snapshot = fetcher._fetch_github_copilot()
        self.assertEqual(snapshot.quota_percent, 75)
        self.assertEqual(fetcher._request.call_args_list[1].args[0], COPILOT_USER_ENDPOINT)

    def test_copilot_identity_without_quota_is_explicitly_unavailable(self) -> None:
        config = AppConfig()
        config.github_copilot.enabled = True
        config.github_copilot.github_token = "test-token"
        config.github_copilot.endpoint_url = COPILOT_USER_ENDPOINT
        fetcher = QuotaFetcher(config, Mock())
        user_response = Mock(status_code=200, headers={})
        user_response.json.return_value = {"login": "test-user"}
        identity_response = Mock(status_code=200, headers={})
        identity_response.json.return_value = {"login": "test-user"}
        fetcher._request = Mock(side_effect=[user_response, identity_response])
        snapshot = fetcher._fetch_github_copilot()
        self.assertIsNone(snapshot.quota_percent)
        self.assertIn("quota endpoint unavailable", snapshot.account_status)


if __name__ == "__main__":
    unittest.main()
