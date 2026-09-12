from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _valid_token(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip()
    return token or None


def _tokens_from_json(value: object) -> list[str]:
    tokens: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {"oauth_token", "oauth-token", "token", "access_token", "access-token"}:
                token = _valid_token(item)
                if token:
                    tokens.append(token)
            tokens.extend(_tokens_from_json(item))
    elif isinstance(value, list):
        for item in value:
            tokens.extend(_tokens_from_json(item))
    return tokens


def token_from_hosts_file(path: Path | None = None) -> str | None:
    hosts_path = path or (
        Path(os.getenv("LOCALAPPDATA", Path.home())) / "github-copilot" / "hosts.json"
    )
    try:
        payload = json.loads(hosts_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    tokens = _tokens_from_json(payload)
    return tokens[0] if tokens else None


def token_from_gh_cli(timeout_seconds: float = 5.0) -> str | None:
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return _valid_token(result.stdout) if result.returncode == 0 else None


def detect_github_token() -> tuple[str | None, str]:
    token = token_from_gh_cli()
    if token:
        return token, "gh"
    token = token_from_hosts_file()
    if token:
        return token, "hosts.json"
    return None, "none"
