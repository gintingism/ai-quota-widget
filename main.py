from __future__ import annotations

import sys

from config_manager import ConfigManager
from tray_icon import TrayIcon
from ui import QuotaWidget


def main() -> None:
    manager = ConfigManager()
    config = manager.load()
    if not config.github_copilot.github_token:
        manager.auto_configure_github_token()
        config = manager.load()
    app: QuotaWidget | None = None
    tray: TrayIcon | None = None

    def exit_app() -> None:
        if app:
            app.save_position()
            app.fetcher.stop()
        if tray:
            tray.stop()
        if app:
            app.after(0, app.destroy)

    app = QuotaWidget(config, manager, exit_app)
    # pystray invokes menu callbacks from its own thread; Tk must be touched
    # only from the GUI thread.
    tray = TrayIcon(
        lambda: app.after(0, app.show),
        lambda: app.after(0, app.open_settings),
        lambda: app.after(0, app.refresh_now),
        lambda: app.after(0, app.toggle_mode),
        exit_app,
    )
    tray.run_in_thread()
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
