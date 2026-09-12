from __future__ import annotations

import sys

from config_manager import ConfigManager


def main() -> int:
    manager = ConfigManager()
    existing = manager.load().github_copilot.github_token
    token = manager.auto_configure_github_token()
    if not token:
        print("GitHub token tidak ditemukan. Pastikan `gh auth login` sudah selesai "
              "atau GitHub Copilot sudah memiliki hosts.json.")
        return 1
    if existing:
        print("GitHub token sudah tersedia di config.json; tidak diubah.")
    else:
        print("GitHub token terdeteksi dan disimpan ke %APPDATA%\\AIQuotaWidget\\config.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
