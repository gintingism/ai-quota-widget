from __future__ import annotations

import ctypes
from ctypes import wintypes
from tkinter import colorchooser, messagebox
from typing import Callable

import customtkinter as ctk

from config_manager import AppConfig, ConfigManager
from quota_fetcher import QuotaFetcher, QuotaSnapshot
from timer_engine import TimerEngine


WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent: "QuotaWidget", config: AppConfig, on_save: Callable[[], None]) -> None:
        super().__init__(parent)
        self.config, self.on_save = config, on_save
        self.title("AI Quota Settings")
        self.geometry("430x610")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self._build()

    def _build(self) -> None:
        ctk.CTkLabel(self, text="Connection & display", font=ctk.CTkFont(size=20, weight="bold")).pack(pady=14)
        frame = ctk.CTkScrollableFrame(self)
        frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.endpoint = self._field(frame, "Quota status endpoint URL", self.config.quota_endpoint)
        self.bearer = self._field(frame, "Bearer token (stored locally)", self.config.bearer_token, True)
        self.session = self._field(frame, "Session token (fallback)", self.config.session_token, True)
        self.cookies = self._field(frame, "Cookies: name=value; name2=value2", self.config.cookies, True)
        self.poll = self._field(frame, "Polling interval (60-3600 seconds)", str(self.config.poll_interval_seconds))
        ctk.CTkLabel(frame, text="Weekly reset day").pack(anchor="w", padx=8, pady=(12, 3))
        self.weekday = ctk.CTkComboBox(frame, values=WEEKDAYS)
        self.weekday.set(WEEKDAYS[self.config.weekly_reset_weekday])
        self.weekday.pack(fill="x", padx=8)
        self.reset_time = self._field(frame, "Local reset time (HH:MM)",
                                       f"{self.config.weekly_reset_hour:02d}:{self.config.weekly_reset_minute:02d}")
        self.always_top = ctk.BooleanVar(value=self.config.always_on_top)
        ctk.CTkCheckBox(frame, text="Always on top", variable=self.always_top).pack(anchor="w", padx=8, pady=10)
        ctk.CTkButton(frame, text="Choose accent color", command=self.choose_color).pack(fill="x", padx=8, pady=4)
        ctk.CTkButton(frame, text="Save", command=self.save).pack(fill="x", padx=8, pady=16)

    @staticmethod
    def _field(parent, label: str, value: str, secret: bool = False) -> ctk.CTkEntry:
        ctk.CTkLabel(parent, text=label).pack(anchor="w", padx=8, pady=(8, 3))
        field = ctk.CTkEntry(parent, show="*" if secret else "")
        field.insert(0, value)
        field.pack(fill="x", padx=8)
        return field

    def choose_color(self) -> None:
        result = colorchooser.askcolor(color=self.config.accent_color, parent=self)
        if result[1]:
            self.config.accent_color = result[1]

    def save(self) -> None:
        try:
            hour, minute = map(int, self.reset_time.get().strip().split(":"))
            interval = int(self.poll.get())
            if not (0 <= hour <= 23 and 0 <= minute <= 59 and 60 <= interval <= 3600):
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid input", "Gunakan HH:MM dan interval 60-3600 detik.", parent=self)
            return
        self.config.quota_endpoint = self.endpoint.get().strip()
        self.config.bearer_token = self.bearer.get().strip()
        self.config.session_token = self.session.get().strip()
        self.config.cookies = self.cookies.get().strip()
        self.config.poll_interval_seconds = interval
        self.config.weekly_reset_weekday = WEEKDAYS.index(self.weekday.get())
        self.config.weekly_reset_hour, self.config.weekly_reset_minute = hour, minute
        self.config.always_on_top = self.always_top.get()
        self.on_save()
        self.destroy()


class QuotaWidget(ctk.CTk):
    def __init__(self, config: AppConfig, manager: ConfigManager, on_exit: Callable[[], None]) -> None:
        super().__init__()
        self.config, self.manager, self.on_exit = config, manager, on_exit
        ctk.set_appearance_mode(config.theme)
        self.title("AI Quota")
        self.overrideredirect(True)
        self.attributes("-alpha", config.window_alpha)
        self.attributes("-topmost", config.always_on_top)
        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.engine = TimerEngine(config.rolling_reset_at, config.weekly_reset_override,
                                  config.weekly_reset_weekday, config.weekly_reset_hour, config.weekly_reset_minute)
        self.expanded = False
        self.last_remote: QuotaSnapshot | None = None
        self.fetcher = QuotaFetcher(config, lambda snapshot: self.after(0, self.apply_remote_snapshot, snapshot))
        self._drag_start: tuple[int, int] | None = None
        self._build()
        self.set_mode()
        self.bind("<ButtonPress-1>", self._drag_begin)
        self.bind("<B1-Motion>", self._drag_move)
        self.bind("<Button-3>", lambda _event: self.open_settings())
        self.after(250, self._tick)
        self.fetcher.start()

    def _build(self) -> None:
        self.card = ctk.CTkFrame(self, corner_radius=12, fg_color=self.config.background_color)
        self.card.pack(fill="both", expand=True)
        self.header = ctk.CTkFrame(self.card, fg_color="transparent")
        self.header.pack(fill="x", padx=12, pady=(7, 0))
        ctk.CTkLabel(self.header, text="AI QUOTA", text_color=self.config.accent_color,
                     font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")
        self.status = ctk.CTkLabel(self.header, text="LOCAL", text_color="#9CA3AF",
                                   font=ctk.CTkFont(size=10))
        self.status.pack(side="left", padx=8)
        ctk.CTkButton(self.header, text="×", width=23, height=22, fg_color="transparent",
                      command=self.hide_to_tray).pack(side="right")
        self.summary = ctk.CTkLabel(self.card, text="Gemini Pro  --%   |   Claude  --%",
                                    font=ctk.CTkFont(size=12, weight="bold"))
        self.summary.pack(pady=(5, 0))
        self.summary.bind("<Button-1>", lambda _event: self.toggle_expand())
        self.reset = ctk.CTkLabel(self.card, text="Reset: --", text_color="#D1D5DB",
                                  font=ctk.CTkFont(size=11))
        self.reset.pack()
        self.details = ctk.CTkFrame(self.card, fg_color="transparent")
        self.details_label = ctk.CTkLabel(self.details, text="Flash --% | Pro --% | Opus --%\nWeekly reset: --\nAccount: --",
                                          justify="left", anchor="w")
        self.details_label.pack(fill="x", padx=14, pady=5)
        self.action = ctk.CTkButton(self.card, text="Triggered Session", height=25,
                                    fg_color=self.config.accent_color, command=self.trigger_session)
        self.action.pack(fill="x", padx=34, pady=(4, 8))

    @staticmethod
    def _format(seconds: int) -> str:
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{days}d {hours:02d}:{minutes:02d}:{secs:02d}" if days else f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def _tick(self) -> None:
        local = self.engine.snapshot()
        remote = self.last_remote
        rolling = remote.rolling_reset_at if remote and remote.rolling_reset_at else self.engine.rolling_reset_at
        weekly = remote.weekly_reset_at if remote and remote.weekly_reset_at else local.weekly_reset_at.timestamp()
        import time
        rolling_left = max(0, int((rolling or time.time()) - time.time()))
        weekly_left = max(0, int(weekly - time.time()))
        self.reset.configure(text=f"Reset: {self._format(rolling_left)}  |  Weekly: {self._format(weekly_left)}")
        self.after(250, self._tick)

    def apply_remote_snapshot(self, snapshot: QuotaSnapshot) -> None:
        self.last_remote = snapshot
        self.status.configure(text="ONLINE" if snapshot.source == "remote" else "LOCAL")
        if snapshot.error:
            self.status.configure(text="OFFLINE")
        values = {model.name.lower(): model.remaining_percent for model in snapshot.models}
        def find(*names: str) -> str:
            for key, value in values.items():
                if any(name in key for name in names) and value is not None:
                    return f"{value:.0f}%"
            return "--%"
        self.summary.configure(text=f"Gemini Pro {find('gemini pro', 'pro')}   |   Claude {find('claude', 'opus')}")
        self.details_label.configure(text=f"Flash {find('flash')} | Pro {find('pro')} | Opus {find('opus', 'claude')}\n"
                                        f"Weekly reset: {self._date(snapshot.weekly_reset_at)}\n"
                                        f"Account: {snapshot.account_status}")

    @staticmethod
    def _date(epoch: float | None) -> str:
        from datetime import datetime
        return datetime.fromtimestamp(epoch).strftime("%d %b %Y %H:%M") if epoch else "--"

    def toggle_expand(self) -> None:
        self.expanded = not self.expanded
        if self.expanded:
            self.details.pack(fill="x")
            self.action.pack(fill="x", padx=34, pady=(4, 8))
        else:
            self.details.pack_forget()
        self.set_mode()

    def set_mode(self) -> None:
        if self.config.ui_mode == "docked":
            work_left, work_top, work_right, work_bottom = self._work_area()
            width, height = (470, 178) if self.expanded else (330, 74)
            self.geometry(f"{470 if self.expanded else 330}x{178 if self.expanded else 74}+"
                          f"{work_right - width - 10}+{work_bottom - height - 6}")
        else:
            self.geometry("470x178" if self.expanded else "330x74")

    @staticmethod
    def _work_area() -> tuple[int, int, int, int]:
        """Return the current monitor work area, excluding the Windows taskbar."""
        try:
            user32 = ctypes.windll.user32
            monitor = user32.MonitorFromPoint(wintypes.POINT(0, 0), 2)
            info = wintypes.MONITORINFO()
            info.cbSize = ctypes.sizeof(info)
            user32.GetMonitorInfoW(monitor, ctypes.byref(info))
            rect = info.rcWork
            return rect.left, rect.top, rect.right, rect.bottom
        except (AttributeError, OSError):
            return 0, 0, 1920, 1040

    def toggle_mode(self) -> None:
        self.config.ui_mode = "floating" if self.config.ui_mode == "docked" else "docked"
        self.manager.save(self.config)
        self.set_mode()

    def trigger_session(self) -> None:
        self.engine.trigger_session()
        self.config.rolling_reset_at = self.engine.rolling_reset_at
        self.manager.save(self.config)

    def force_reset(self) -> None:
        self.engine.force_reset()
        self.config.rolling_reset_at = self.engine.rolling_reset_at
        self.manager.save(self.config)

    def refresh_now(self) -> None:
        self.fetcher.refresh_now()

    def _drag_begin(self, event) -> None:
        self._drag_start = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())

    def _drag_move(self, event) -> None:
        if self._drag_start and self.config.ui_mode == "floating":
            self.geometry(f"+{event.x_root - self._drag_start[0]}+{event.y_root - self._drag_start[1]}")

    def save_position(self) -> None:
        self.config.window_x, self.config.window_y = self.winfo_x(), self.winfo_y()
        self.manager.save(self.config)

    def show(self) -> None:
        self.deiconify()
        self.lift()

    def hide_to_tray(self) -> None:
        self.save_position()
        self.withdraw()

    def open_settings(self) -> None:
        SettingsWindow(self, self.config, self._settings_saved)

    def _settings_saved(self) -> None:
        self.fetcher.stop()
        self.fetcher = QuotaFetcher(self.config, lambda snapshot: self.after(0, self.apply_remote_snapshot, snapshot))
        self.fetcher.start()
        self.attributes("-topmost", self.config.always_on_top)
        self.manager.save(self.config)
        self.show()
