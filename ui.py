from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from datetime import datetime
from tkinter import colorchooser, messagebox
from typing import Callable

import customtkinter as ctk

from config_manager import AppConfig, ConfigManager
from quota_fetcher import AggregatedQuotaState, ProviderSnapshot, QuotaFetcher
from timer_engine import TimerEngine


WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent: "QuotaWidget", config: AppConfig,
                 on_save: Callable[[], None], focus_provider: str | None = None) -> None:
        super().__init__(parent)
        self.config, self.on_save = config, on_save
        self.title("AI Quota Settings")
        self.geometry("450x670")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self._build(focus_provider)

    def _build(self, focus_provider: str | None) -> None:
        ctk.CTkLabel(self, text="Provider credentials",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(pady=14)
        frame = ctk.CTkScrollableFrame(self)
        frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        ctk.CTkLabel(frame, text="Re-auth provider").pack(anchor="w", padx=8, pady=(4, 3))
        self.provider = ctk.CTkComboBox(frame, values=["Antigravity", "GitHub Copilot"])
        self.provider.set("GitHub Copilot" if focus_provider == "github_copilot" else "Antigravity")
        self.provider.pack(fill="x", padx=8)
        self.antigravity_enabled = ctk.BooleanVar(value=self.config.antigravity.enabled)
        ctk.CTkCheckBox(frame, text="Enable Antigravity",
                        variable=self.antigravity_enabled).pack(anchor="w", padx=8, pady=(12, 3))
        self.ag_endpoint = self._field(frame, "Antigravity endpoint URL",
                                       self.config.antigravity.endpoint_url)
        self.ag_token = self._field(frame, "Antigravity session token",
                                    self.config.antigravity.session_token, True)
        self.ag_cookies = self._field(frame, "Antigravity cookies: name=value; name2=value2",
                                      self.config.antigravity.cookies, True)
        self.ag_interval = self._field(frame, "Antigravity refresh interval (60-3600 sec)",
                                       str(self.config.antigravity.refresh_interval_sec))
        self.copilot_enabled = ctk.BooleanVar(value=self.config.github_copilot.enabled)
        ctk.CTkCheckBox(frame, text="Enable GitHub Copilot",
                        variable=self.copilot_enabled).pack(anchor="w", padx=8, pady=(12, 3))
        self.gh_token = self._field(frame, "GitHub token",
                                    self.config.github_copilot.github_token, True)
        self.gh_endpoint = self._field(frame, "GitHub Copilot endpoint",
                                       self.config.github_copilot.endpoint_url)
        self.gh_editor = self._field(frame, "Editor-Version header",
                                     self.config.github_copilot.editor_version)
        self.gh_interval = self._field(frame, "GitHub refresh interval (60-3600 sec)",
                                       str(self.config.github_copilot.refresh_interval_sec))
        self.reset_time = self._field(frame, "Fallback weekly reset time (HH:MM)",
                                       f"{self.config.weekly_reset_hour:02d}:{self.config.weekly_reset_minute:02d}")
        ctk.CTkLabel(frame, text="Fallback weekly reset day").pack(anchor="w", padx=8, pady=(10, 3))
        self.weekday = ctk.CTkComboBox(frame, values=WEEKDAYS)
        self.weekday.set(WEEKDAYS[self.config.weekly_reset_weekday])
        self.weekday.pack(fill="x", padx=8)
        self.always_top = ctk.BooleanVar(value=self.config.always_on_top)
        ctk.CTkCheckBox(frame, text="Always on top",
                        variable=self.always_top).pack(anchor="w", padx=8, pady=10)
        ctk.CTkButton(frame, text="Choose accent color",
                      command=self.choose_color).pack(fill="x", padx=8, pady=4)
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
            ag_interval = int(self.ag_interval.get())
            gh_interval = int(self.gh_interval.get())
            if not (0 <= hour <= 23 and 0 <= minute <= 59
                    and 60 <= ag_interval <= 3600 and 60 <= gh_interval <= 3600):
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid input",
                                 "Gunakan HH:MM dan interval 60-3600 detik.",
                                 parent=self)
            return
        ag = self.config.antigravity
        ag.enabled, ag.endpoint_url = self.antigravity_enabled.get(), self.ag_endpoint.get().strip()
        ag.session_token, ag.cookies = self.ag_token.get().strip(), self.ag_cookies.get().strip()
        ag.refresh_interval_sec = ag_interval
        gh = self.config.github_copilot
        gh.enabled, gh.github_token = self.copilot_enabled.get(), self.gh_token.get().strip()
        gh.endpoint_url, gh.editor_version = self.gh_endpoint.get().strip(), self.gh_editor.get().strip()
        gh.refresh_interval_sec = gh_interval
        self.config.weekly_reset_weekday = WEEKDAYS.index(self.weekday.get())
        self.config.weekly_reset_hour, self.config.weekly_reset_minute = hour, minute
        self.config.always_on_top = self.always_top.get()
        self.on_save()
        self.destroy()


class QuotaWidget(ctk.CTk):
    def __init__(self, config: AppConfig, manager: ConfigManager,
                 on_exit: Callable[[], None]) -> None:
        super().__init__()
        self.config, self.manager, self.on_exit = config, manager, on_exit
        ctk.set_appearance_mode(config.theme)
        self.title("AI Quota")
        self.overrideredirect(True)
        self.attributes("-alpha", config.window_alpha)
        self.attributes("-topmost", config.always_on_top)
        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.engine = TimerEngine(config.rolling_reset_at, config.weekly_reset_override,
                                  config.weekly_reset_weekday, config.weekly_reset_hour,
                                  config.weekly_reset_minute)
        self.expanded = False
        self.last_state = AggregatedQuotaState()
        self.fetcher = QuotaFetcher(
            config, lambda state: self.after(0, self.apply_state, state)
        )
        self._drag_start: tuple[int, int] | None = None
        self._build()
        self.set_mode()
        self.bind("<ButtonPress-1>", self._drag_begin)
        self.bind("<B1-Motion>", self._drag_move)
        self.bind("<Button-3>", lambda _event: self.open_settings())
        self.after(250, self._tick)
        self.fetcher.start()

    def _build(self) -> None:
        self.card = ctk.CTkFrame(self, corner_radius=12,
                                 fg_color=self.config.background_color)
        self.card.pack(fill="both", expand=True)
        header = ctk.CTkFrame(self.card, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(7, 0))
        ctk.CTkLabel(header, text="AI QUOTA",
                     text_color=self.config.accent_color,
                     font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")
        self.status = ctk.CTkLabel(header, text="LOCAL",
                                   text_color="#9CA3AF",
                                   font=ctk.CTkFont(size=10))
        self.status.pack(side="left", padx=8)
        ctk.CTkButton(header, text="×", width=23, height=22,
                      fg_color="transparent",
                      command=self.hide_to_tray).pack(side="right")
        self.summary = ctk.CTkLabel(
            self.card, text="Antigravity --%   |   Copilot --%",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.summary.pack(pady=(5, 0))
        self.summary.bind("<Button-1>", lambda _event: self.toggle_expand())
        self.reset = ctk.CTkLabel(self.card, text="Nearest reset: --",
                                  text_color="#D1D5DB",
                                  font=ctk.CTkFont(size=11))
        self.reset.pack()
        self.details = ctk.CTkFrame(self.card, fg_color="transparent")
        self.ag_details = ctk.CTkLabel(self.details, text="", justify="left",
                                       anchor="w")
        self.ag_details.pack(fill="x", padx=14, pady=(5, 2))
        self.gh_details = ctk.CTkLabel(self.details, text="", justify="left",
                                       anchor="w")
        self.gh_details.pack(fill="x", padx=14, pady=(2, 5))
        self.action = ctk.CTkButton(
            self.card, text="Triggered Session", height=25,
            fg_color=self.config.accent_color, command=self.trigger_session
        )

    @staticmethod
    def _format(seconds: int) -> str:
        days, remainder = divmod(max(0, seconds), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        return (f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"
                if days else f"{hours:02d}:{minutes:02d}:{seconds:02d}")

    @staticmethod
    def _date(epoch: float | None) -> str:
        return datetime.fromtimestamp(epoch).strftime("%d %b %Y %H:%M") if epoch else "--"

    @staticmethod
    def _model_percent(snapshot: ProviderSnapshot, *names: str) -> str:
        for model in snapshot.models:
            if any(name in model.name.lower() for name in names):
                if model.remaining_percent is not None:
                    return f"{model.remaining_percent:.0f}%"
        return "--%"

    def _tick(self) -> None:
        ag = self.last_state.providers.get("antigravity")
        local = self.engine.snapshot()
        rolling = ag.rolling_reset_at if ag and ag.rolling_reset_at else self.engine.rolling_reset_at
        weekly = ag.weekly_reset_at if ag and ag.weekly_reset_at else local.weekly_reset_at.timestamp()
        now = time.time()
        values = [value for value in (rolling, weekly) if value and value > now]
        nearest = min(values) if values else None
        self.reset.configure(text=f"Nearest reset: {self._format(int(nearest - now))}"
                             if nearest else "Nearest reset: --")
        self.after(250, self._tick)

    def apply_state(self, state: AggregatedQuotaState) -> None:
        self.last_state = state
        ag = state.providers.get("antigravity", ProviderSnapshot("antigravity"))
        gh = state.providers.get("github_copilot", ProviderSnapshot("github_copilot"))
        errors = [snapshot.error for snapshot in (ag, gh) if snapshot.error]
        self.status.configure(text="OFFLINE" if errors else "ONLINE")
        self.summary.configure(
            text=f"Antigravity {self._model_percent(ag, 'gemini pro', 'pro')}   |   "
                 f"Copilot {f'{gh.quota_percent:.0f}%' if gh.quota_percent is not None else '--%'}"
        )
        ag_status = ag.error or ag.account_status
        self.ag_details.configure(
            text=f"ANTIGRAVITY  [{ag_status}]\n"
                 f"Gemini Pro {self._model_percent(ag, 'gemini pro', 'pro')} | "
                 f"Flash {self._model_percent(ag, 'flash')} | "
                 f"Claude {self._model_percent(ag, 'claude', 'opus')}\n"
                 f"Rolling 5h reset: {self._date(ag.rolling_reset_at)} | "
                 f"Weekly: {self._date(ag.weekly_reset_at)}"
        )
        self.gh_details.configure(
            text=f"GITHUB COPILOT  [{gh.error or gh.account_status}]\n"
                 f"Monthly/completions quota: "
                 f"{f'{gh.quota_percent:.0f}%' if gh.quota_percent is not None else '--%'} | "
                 f"Reset: {self._date(gh.reset_at)} | Plan: {gh.plan_tier}"
        )

    def toggle_expand(self) -> None:
        self.expanded = not self.expanded
        if self.expanded:
            self.details.pack(fill="x")
            self.action.pack(fill="x", padx=34, pady=(4, 8))
        else:
            self.details.pack_forget()
            self.action.pack_forget()
        self.set_mode()

    def set_mode(self) -> None:
        width, height = (500, 230) if self.expanded else (330, 74)
        if self.config.ui_mode == "docked":
            _, _, right, bottom = self._work_area()
            self.geometry(f"{width}x{height}+{right - width - 10}+{bottom - height - 6}")
        else:
            self.geometry(f"{width}x{height}")

    @staticmethod
    def _work_area() -> tuple[int, int, int, int]:
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

    def refresh_now(self) -> None:
        self.fetcher.refresh_now()

    def _drag_begin(self, event) -> None:
        self._drag_start = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())

    def _drag_move(self, event) -> None:
        if self._drag_start and self.config.ui_mode == "floating":
            self.geometry(f"+{event.x_root - self._drag_start[0]}+"
                          f"{event.y_root - self._drag_start[1]}")

    def save_position(self) -> None:
        self.config.window_x, self.config.window_y = self.winfo_x(), self.winfo_y()
        self.manager.save(self.config)

    def show(self) -> None:
        self.deiconify()
        self.lift()

    def hide_to_tray(self) -> None:
        self.save_position()
        self.withdraw()

    def open_settings(self, focus_provider: str | None = None) -> None:
        SettingsWindow(self, self.config, self._settings_saved, focus_provider)

    def _settings_saved(self) -> None:
        self.fetcher.stop()
        self.fetcher = QuotaFetcher(
            self.config, lambda state: self.after(0, self.apply_state, state)
        )
        self.fetcher.start()
        self.attributes("-topmost", self.config.always_on_top)
        self.manager.save(self.config)
        self.show()
