from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import tkinter as tk
import webbrowser
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Any

from telethon import TelegramClient, functions, types, utils
from telethon.errors import (
    ApiIdInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

from . import __version__
from .config import (
    AppConfig,
    ConfigurationError,
    default_config_path,
    default_draft_config_path,
    default_session_path,
    load_partial,
)
from .lastfm import LastFmClient, LastFmError
from .localization import LANGUAGE_LABELS, normalize_language, translate
from .telegram import TelegramError, _emoji_status_for_update

LASTFM_API_ACCOUNT_URL = "https://www.last.fm/api/account/create"
WEB_SCROBBLER_URL = "https://webscrobbler.com/"
log = logging.getLogger(__name__)


class SetupWizard:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or default_config_path()
        self.session_path = default_session_path()
        if self.config_path.is_file():
            config = load_partial(self.config_path)
        else:
            config = load_partial(default_draft_config_path())
        self.root = tk.Tk()
        self.root.geometry("920x840")
        self.root.minsize(820, 740)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.root.option_add("*tearOff", False)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.bind("<Control-s>", lambda _event: self._save())
        self.root.bind("<Escape>", lambda _event: self._cancel())
        self.saved = False
        self._phone_code_hash: str | None = None
        self.ui_language = tk.StringVar(
            value=normalize_language(config.ui_language)
        )
        self.language_display = tk.StringVar(
            value=LANGUAGE_LABELS[normalize_language(config.ui_language)]
        )
        self.dark_mode = tk.BooleanVar(value=config.ui_theme != "light")

        self.lastfm_username = tk.StringVar(value=config.lastfm_username)
        self.lastfm_api_key = tk.StringVar(value=config.lastfm_api_key)
        self.telegram_api_id = tk.StringVar(
            value=str(config.telegram_api_id) if config.telegram_api_id else ""
        )
        self.telegram_api_hash = tk.StringVar(value=config.telegram_api_hash)
        self.telegram_phone = tk.StringVar(value=config.telegram_phone)
        self.telegram_code = tk.StringVar()
        self.telegram_password = tk.StringVar()
        self.show_api_credentials = tk.BooleanVar(value=False)
        self.poll_interval = tk.StringVar(value=str(config.poll_interval_seconds))
        self.absent_confirmations = tk.StringVar(value=str(config.absent_confirmations))
        self.cache_size = tk.StringVar(value=str(config.cache_size))
        self.audio_mode = tk.StringVar(value=config.audio_mode)
        self.download_workers = tk.StringVar(value=str(config.download_workers))
        self.remove_when_idle = tk.BooleanVar(value=config.remove_when_idle)
        self.telegram_output_mode = tk.StringVar(
            value=config.telegram_output_mode
        )
        self.telegram_personal_channel_id = tk.StringVar(
            value=(
                str(config.telegram_personal_channel_id)
                if config.telegram_personal_channel_id
                else ""
            )
        )
        self.telegram_playing_emoji_enabled = tk.BooleanVar(
            value=config.telegram_playing_emoji_enabled
        )
        self.telegram_playing_emoji_id = tk.StringVar(
            value=(
                str(config.telegram_playing_emoji_id)
                if config.telegram_playing_emoji_id
                else ""
            )
        )
        self.notifications_enabled = tk.BooleanVar(value=config.notifications_enabled)
        self.notification_sound_enabled = tk.BooleanVar(
            value=config.notification_sound_enabled
        )
        self.status = tk.StringVar(value=self._t("status.initial"))
        self._status_state = "info"
        self._indicator_images: dict[str, tuple[tk.PhotoImage, ...]] = {}
        self._button_animations: dict[str, str] = {}
        self._button_styles: dict[str, tuple[str, str]] = {}
        self._button_style_serial = 0

        self._configure_style()
        self._build()
        self.root.bind("<MouseWheel>", self._scroll_sync_page)
        self.root.bind_class(
            "TButton",
            "<Enter>",
            self._start_button_hover,
            add="+",
        )
        self.root.bind_class(
            "TButton",
            "<Leave>",
            self._stop_button_hover,
            add="+",
        )
        self.root.after(150, self._check_telegram_session)

    def run(self) -> bool:
        self.root.mainloop()
        return self.saved

    def _t(self, key: str, **values: object) -> str:
        return translate(key, self.ui_language.get(), **values)

    def _change_language(self, _event: tk.Event[tk.Misc]) -> None:
        selected = self.language_display.get()
        language = next(
            (
                code
                for code, label in LANGUAGE_LABELS.items()
                if label == selected
            ),
            normalize_language(self.ui_language.get()),
        )
        if language == self.ui_language.get():
            return
        selected_tab = self._notebook.index("current")
        self.ui_language.set(language)
        self._set_status(self._t("status.language_changed"), "info")
        self._cancel_button_animations()
        self._outer.destroy()
        self._build()
        self._notebook.select(selected_tab)

    def _toggle_theme(self) -> None:
        selected_tab = self._notebook.index("current")
        self._cancel_button_animations()
        self._outer.destroy()
        self._configure_style()
        self._build()
        self._notebook.select(selected_tab)

    def _update_sync_scroll_region(
        self,
        _event: tk.Event[tk.Misc] | None = None,
    ) -> None:
        bbox = self._sync_canvas.bbox("all")
        if bbox is None:
            return
        self._sync_canvas.configure(scrollregion=bbox)
        if bbox[3] - bbox[1] > self._sync_canvas.winfo_height() + 1:
            self._sync_scrollbar.grid()
        else:
            self._sync_scrollbar.grid_remove()
            self._sync_canvas.yview_moveto(0)

    def _resize_sync_content(self, event: tk.Event[tk.Misc]) -> None:
        self._sync_canvas.itemconfigure(self._sync_window, width=event.width)
        self._update_sync_scroll_region()

    def _scroll_sync_page(self, event: tk.Event[tk.Misc]) -> str | None:
        if self._notebook.index("current") != 2:
            return None
        if not self._sync_scrollbar.winfo_ismapped():
            return None
        delta = int(getattr(event, "delta", 0))
        if delta == 0:
            return None
        steps = -max(-3, min(3, delta // 120))
        self._sync_canvas.yview_scroll(steps, "units")
        return "break"

    def _start_button_hover(self, event: tk.Event[tk.Misc]) -> None:
        button = event.widget
        if not isinstance(button, ttk.Button) or button.instate(["disabled"]):
            return
        original, animated = self._animated_button_style(button)
        colors = self._theme_colors
        if original == "Accent.TButton":
            target_background = colors["accent_hover"]
            target_border = colors["accent_hover"]
        else:
            target_background = colors["button_hover"]
            target_border = colors["accent"]
        self._animate_button(
            button,
            animated,
            target_background,
            target_border,
        )

    def _stop_button_hover(self, event: tk.Event[tk.Misc]) -> None:
        button = event.widget
        if not isinstance(button, ttk.Button):
            return
        original, animated = self._animated_button_style(button)
        colors = self._theme_colors
        if original == "Accent.TButton":
            target_background = colors["accent"]
            target_border = colors["accent"]
        else:
            target_background = colors["button"]
            target_border = colors["border"]
        self._animate_button(
            button,
            animated,
            target_background,
            target_border,
        )

    def _animated_button_style(self, button: ttk.Button) -> tuple[str, str]:
        key = str(button)
        existing = self._button_styles.get(key)
        if existing is not None:
            return existing
        original = str(button.cget("style") or "TButton")
        self._button_style_serial += 1
        if original == "TButton":
            animated = f"Animated{self._button_style_serial}.TButton"
        else:
            animated = f"Animated{self._button_style_serial}.{original}"
        colors = self._theme_colors
        self._style.configure(
            animated,
            background=self._style.lookup(original, "background"),
            bordercolor=self._style.lookup(original, "bordercolor"),
        )
        self._style.map(
            animated,
            background=[
                ("disabled", colors["field_disabled"]),
                ("pressed", colors["accent_pressed"]),
            ],
            foreground=[("disabled", colors["disabled"])],
            bordercolor=[
                ("disabled", colors["border"]),
                ("pressed", colors["accent_pressed"]),
            ],
        )
        button.configure(style=animated)
        result = (original, animated)
        self._button_styles[key] = result
        return result

    def _animate_button(
        self,
        button: ttk.Button,
        style_name: str,
        target_background: str,
        target_border: str,
    ) -> None:
        key = str(button)
        pending = self._button_animations.pop(key, None)
        if pending is not None:
            self.root.after_cancel(pending)
        start_background = self._style.lookup(style_name, "background")
        start_border = self._style.lookup(style_name, "bordercolor")
        frames = 7

        def render(frame: int) -> None:
            try:
                self._style.configure(
                    style_name,
                    background=_mix_color(
                        start_background,
                        target_background,
                        frame / frames,
                    ),
                    bordercolor=_mix_color(
                        start_border,
                        target_border,
                        frame / frames,
                    ),
                )
            except tk.TclError:
                self._button_animations.pop(key, None)
                return
            if frame < frames:
                self._button_animations[key] = self.root.after(
                    18,
                    render,
                    frame + 1,
                )
            else:
                self._button_animations.pop(key, None)

        render(1)

    def _cancel_button_animations(self) -> None:
        for after_id in self._button_animations.values():
            self.root.after_cancel(after_id)
        self._button_animations.clear()
        self._button_styles.clear()

    def _build(self) -> None:
        self.root.title(self._t("window.title", version=__version__))
        outer = ttk.Frame(
            self.root,
            padding=(28, 18, 28, 18),
            style="App.TFrame",
        )
        self._outer = outer
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        header = ttk.Frame(outer, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        ttk.Label(header, text="♫", style="Logo.TLabel").pack(side=tk.LEFT)
        heading = ttk.Frame(header, style="App.TFrame")
        heading.pack(side=tk.LEFT, padx=(12, 0))
        ttk.Label(
            heading,
            text="YT Music → Telegram",
            style="Title.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            heading,
            text=self._t("header.subtitle"),
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        header_actions = ttk.Frame(header, style="App.TFrame")
        header_actions.pack(side=tk.RIGHT, anchor="n")
        ttk.Label(
            header_actions,
            text=f"v{__version__}",
            style="Version.TLabel",
        ).pack(side=tk.RIGHT, padx=(14, 0), pady=(8, 0))
        ttk.Checkbutton(
            header_actions,
            text=self._t("theme.dark"),
            variable=self.dark_mode,
            command=self._toggle_theme,
            style="Header.TCheckbutton",
        ).pack(side=tk.LEFT, padx=(0, 14), pady=(5, 0))
        ttk.Label(
            header_actions,
            text=self._t("language.label"),
            style="Hint.TLabel",
        ).pack(side=tk.LEFT, padx=(0, 7), pady=(8, 0))
        language = ttk.Combobox(
            header_actions,
            textvariable=self.language_display,
            values=tuple(LANGUAGE_LABELS.values()),
            state="readonly",
            width=9,
        )
        language.pack(side=tk.LEFT, pady=(2, 0))
        language.bind("<<ComboboxSelected>>", self._change_language)

        notebook = ttk.Notebook(outer, style="App.TNotebook")
        self._notebook = notebook
        notebook.grid(row=1, column=0, sticky="nsew")
        lastfm_page = ttk.Frame(
            notebook,
            padding=(16, 18),
            style="Page.TFrame",
        )
        telegram_page = ttk.Frame(
            notebook,
            padding=(16, 18),
            style="Page.TFrame",
        )
        synchronization_page = ttk.Frame(
            notebook,
            style="Page.TFrame",
        )
        synchronization_page.columnconfigure(0, weight=1)
        synchronization_page.rowconfigure(0, weight=1)
        self._sync_canvas = tk.Canvas(
            synchronization_page,
            background=self._theme_colors["page"],
            borderwidth=0,
            highlightthickness=0,
            height=560,
        )
        self._sync_canvas.grid(row=0, column=0, sticky="nsew")
        self._sync_scrollbar = ttk.Scrollbar(
            synchronization_page,
            orient=tk.VERTICAL,
            command=self._sync_canvas.yview,
        )
        self._sync_scrollbar.grid(row=0, column=1, sticky="ns")
        self._sync_canvas.configure(yscrollcommand=self._sync_scrollbar.set)
        synchronization = ttk.Frame(
            self._sync_canvas,
            padding=(16, 18),
            style="Page.TFrame",
        )
        self._sync_window = self._sync_canvas.create_window(
            (0, 0),
            window=synchronization,
            anchor="nw",
        )
        synchronization.bind("<Configure>", self._update_sync_scroll_region)
        self._sync_canvas.bind("<Configure>", self._resize_sync_content)
        notebook.add(lastfm_page, text="  Last.fm  ")
        notebook.add(telegram_page, text="  Telegram  ")
        notebook.add(synchronization_page, text=self._t("tabs.sync"))

        lastfm = ttk.LabelFrame(
            lastfm_page,
            text="Last.fm",
            padding=(18, 16),
            style="Card.TLabelframe",
        )
        lastfm.pack(fill=tk.X)
        self._entry(lastfm, 0, self._t("lastfm.username"), self.lastfm_username)
        self._lastfm_api_key_entry = self._entry(
            lastfm,
            1,
            "API key",
            self.lastfm_api_key,
            show="•",
        )
        note = ttk.Label(
            lastfm,
            text=self._t("lastfm.note"),
            wraplength=620,
            style="Muted.Card.TLabel",
        )
        note.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 4))
        ttk.Checkbutton(
            lastfm,
            text=self._t("credentials.show"),
            variable=self.show_api_credentials,
            command=self._update_secret_visibility,
            style="Card.TCheckbutton",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 8))
        buttons = ttk.Frame(lastfm, style="Card.TFrame")
        buttons.grid(row=4, column=0, columnspan=3, sticky="w")
        ttk.Button(
            buttons,
            text=self._t("lastfm.get_api_key"),
            command=self._open_api_page,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(buttons, text="Web Scrobbler", command=self._open_scrobbler).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(
            buttons,
            text=self._t("lastfm.test"),
            command=self._test_lastfm,
            style="Accent.TButton",
        ).pack(side=tk.LEFT)

        telegram = ttk.LabelFrame(
            telegram_page,
            text="Telegram",
            padding=(18, 16),
            style="Card.TLabelframe",
        )
        telegram.pack(fill=tk.X)
        self._entry(telegram, 0, "API ID", self.telegram_api_id)
        self._telegram_api_hash_entry = self._entry(
            telegram,
            1,
            "API hash",
            self.telegram_api_hash,
            show="•",
        )
        self._telegram_phone_entry = self._entry(
            telegram,
            2,
            self._t("telegram.phone"),
            self.telegram_phone,
            show="•",
        )
        ttk.Button(
            telegram,
            text=self._t("telegram.send_code"),
            command=self._send_telegram_code,
        ).grid(row=3, column=0, sticky="w", pady=(8, 2))
        ttk.Checkbutton(
            telegram,
            text=self._t("credentials.show"),
            variable=self.show_api_credentials,
            command=self._update_secret_visibility,
            style="Card.TCheckbutton",
        ).grid(row=3, column=1, columnspan=2, sticky="w", padx=(8, 0))
        self._entry(telegram, 4, self._t("telegram.code"), self.telegram_code)
        self._entry(
            telegram,
            5,
            self._t("telegram.password"),
            self.telegram_password,
            show="•",
        )
        ttk.Button(
            telegram,
            text=self._t("telegram.sign_in"),
            command=self._sign_in_telegram,
        ).grid(row=6, column=0, sticky="w", pady=(8, 2))
        ttk.Label(
            telegram,
            text=self._t("telegram.password_note"),
            style="Muted.Card.TLabel",
        ).grid(row=6, column=1, columnspan=2, sticky="w", padx=(8, 0))

        behavior = ttk.LabelFrame(
            synchronization,
            text=self._t("behavior.title"),
            padding=(18, 16),
            style="Card.TLabelframe",
        )
        behavior.pack(fill=tk.X)
        behavior.columnconfigure(0, minsize=225)
        behavior.columnconfigure(1, weight=1)
        self._entry(behavior, 0, self._t("behavior.poll"), self.poll_interval)
        self._entry(behavior, 1, self._t("behavior.absent"), self.absent_confirmations)
        self._cache_size_entry = self._entry(
            behavior, 2, self._t("behavior.cache"), self.cache_size
        )
        ttk.Label(
            behavior,
            text=self._t("behavior.audio_mode"),
            style="Card.TLabel",
        ).grid(
            row=3, column=0, sticky="w", padx=(0, 12), pady=4
        )
        mode = ttk.Combobox(
            behavior,
            textvariable=self.audio_mode,
            values=("placeholder", "mixed", "audio"),
            state="readonly",
            width=28,
        )
        mode.grid(row=3, column=1, columnspan=2, sticky="ew", pady=5)
        ttk.Label(
            behavior,
            text=self._t("behavior.output_mode"),
            style="Card.TLabel",
        ).grid(row=4, column=0, sticky="w", padx=(0, 12), pady=5)
        output_mode = ttk.Frame(behavior, style="Card.TFrame")
        output_mode.grid(row=4, column=1, columnspan=2, sticky="ew", pady=5)
        for column in range(3):
            output_mode.columnconfigure(column, weight=1, uniform="output-mode")
        ttk.Radiobutton(
            output_mode,
            text=self._t("behavior.output_profile"),
            variable=self.telegram_output_mode,
            value="profile_music",
            command=self._update_output_controls,
            style="Segment.TRadiobutton",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 3))
        ttk.Radiobutton(
            output_mode,
            text=self._t("behavior.output_channel"),
            variable=self.telegram_output_mode,
            value="personal_channel",
            command=self._update_output_controls,
            style="Segment.TRadiobutton",
        ).grid(row=0, column=1, sticky="ew", padx=3)
        ttk.Radiobutton(
            output_mode,
            text=self._t("behavior.output_both"),
            variable=self.telegram_output_mode,
            value="profile_and_channel",
            command=self._update_output_controls,
            style="Segment.TRadiobutton",
        ).grid(row=0, column=2, sticky="ew", padx=(3, 0))
        ttk.Label(
            behavior,
            text=self._t("behavior.channel"),
            style="Card.TLabel",
        ).grid(row=5, column=0, sticky="w", padx=(0, 12), pady=4)
        self._personal_channel_entry = ttk.Entry(
            behavior,
            textvariable=self.telegram_personal_channel_id,
            width=28,
        )
        self._personal_channel_entry.grid(row=5, column=1, sticky="ew", pady=4)
        self._personal_channel_button = ttk.Button(
            behavior,
            text=self._t("behavior.select"),
            command=self._select_personal_channel,
            style="Select.TButton",
        )
        self._personal_channel_button.grid(
            row=5, column=2, sticky="e", padx=(8, 0), pady=4
        )
        ttk.Checkbutton(
            behavior,
            text=self._t("behavior.emoji"),
            variable=self.telegram_playing_emoji_enabled,
            command=self._update_emoji_controls,
            style="Card.TCheckbutton",
        ).grid(
            row=6, column=0, sticky="w", padx=(0, 12), pady=4
        )
        self._playing_emoji_entry = ttk.Entry(
            behavior,
            textvariable=self.telegram_playing_emoji_id,
            width=28,
        )
        self._playing_emoji_entry.grid(row=6, column=1, sticky="ew", pady=4)
        self._playing_emoji_button = ttk.Button(
            behavior,
            text=self._t("behavior.select"),
            command=self._select_playing_emoji,
            style="Select.TButton",
        )
        self._playing_emoji_button.grid(
            row=6, column=2, sticky="e", padx=(8, 0), pady=4
        )
        self._entry(
            behavior,
            7,
            self._t("behavior.workers"),
            self.download_workers,
        )
        self._remove_when_idle_checkbox = ttk.Checkbutton(
            behavior,
            text=self._t("behavior.remove_idle"),
            variable=self.remove_when_idle,
            style="Card.TCheckbutton",
        )
        self._remove_when_idle_checkbox.grid(
            row=8, column=0, columnspan=3, sticky="w", pady=(6, 0)
        )
        self._update_output_controls()

        notifications = ttk.LabelFrame(
            synchronization,
            text=self._t("notifications.title"),
            padding=(18, 16),
            style="Card.TLabelframe",
        )
        notifications.pack(fill=tk.X, pady=(18, 0))
        ttk.Checkbutton(
            notifications,
            text=self._t("notifications.enabled"),
            variable=self.notifications_enabled,
            command=self._update_notification_controls,
            style="Card.TCheckbutton",
        ).grid(row=0, column=0, sticky="w")
        self._notification_sound_checkbox = ttk.Checkbutton(
            notifications,
            text=self._t("notifications.sound"),
            variable=self.notification_sound_enabled,
            style="Card.TCheckbutton",
        )
        self._notification_sound_checkbox.grid(
            row=1,
            column=0,
            sticky="w",
            pady=(8, 0),
        )
        ttk.Label(
            notifications,
            text=self._t("notifications.note"),
            style="Muted.Card.TLabel",
        ).grid(row=2, column=0, sticky="w", pady=(8, 0))
        self._update_notification_controls()

        status_bar = ttk.Frame(
            outer,
            padding=(14, 10),
            style="Status.TFrame",
        )
        status_bar.grid(row=2, column=0, sticky="ew", pady=(14, 10))
        status_bar.columnconfigure(1, weight=1)
        self._status_indicator = ttk.Label(
            status_bar,
            text="●",
            style="Info.StatusIcon.TLabel",
            anchor="center",
        )
        self._status_indicator.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        ttk.Label(
            status_bar,
            textvariable=self.status,
            wraplength=760,
            style="Status.TLabel",
            anchor="w",
            justify=tk.LEFT,
        ).grid(row=0, column=1, sticky="ew")
        self._refresh_status_indicator()

        footer = ttk.Frame(outer, style="App.TFrame")
        footer.grid(row=3, column=0, sticky="ew", pady=(0, 2))
        footer_actions = ttk.Frame(footer, style="App.TFrame")
        footer_actions.pack(side=tk.RIGHT)
        ttk.Label(
            footer_actions,
            text=self._t("footer.hint"),
            style="Hint.TLabel",
        ).pack(side=tk.LEFT, padx=(0, 18), pady=9)
        ttk.Button(
            footer_actions,
            text=self._t("footer.cancel"),
            command=self._cancel,
        ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(
            footer_actions,
            text=self._t("footer.save"),
            command=self._save,
            style="Accent.TButton",
        ).pack(side=tk.LEFT)

    def _configure_style(self) -> None:
        theme = "dark" if self.dark_mode.get() else "light"
        palettes = {
            "dark": {
                "background": "#12131A",
                "page": "#1E1E2E",
                "card": "#252630",
                "field": "#1A1B25",
                "field_disabled": "#20212B",
                "text": "#E2E8F0",
                "muted": "#94A3B8",
                "disabled": "#64748B",
                "border": "#334155",
                "accent": "#3B82F6",
                "accent_hover": "#2563EB",
                "accent_pressed": "#1D4ED8",
                "button": "#2B2D3A",
                "button_hover": "#343747",
                "tab": "#191A24",
                "status": "#18263D",
                "success": "#22C55E",
                "warning": "#F59E0B",
                "error": "#EF4444",
            },
            "light": {
                "background": "#EEF2F7",
                "page": "#F5F7FB",
                "card": "#FFFFFF",
                "field": "#F8FAFC",
                "field_disabled": "#E7ECF3",
                "text": "#172033",
                "muted": "#64748B",
                "disabled": "#94A3B8",
                "border": "#CBD5E1",
                "accent": "#3B82F6",
                "accent_hover": "#2563EB",
                "accent_pressed": "#1D4ED8",
                "button": "#E2E8F0",
                "button_hover": "#D5DDE8",
                "tab": "#E4E9F1",
                "status": "#E5EEF9",
                "success": "#16A34A",
                "warning": "#D97706",
                "error": "#DC2626",
            },
        }
        colors = palettes[theme]
        self._theme_colors = colors
        background = colors["background"]
        page = colors["page"]
        card = colors["card"]
        text = colors["text"]
        muted = colors["muted"]
        border = colors["border"]
        accent = colors["accent"]

        self.root.configure(background=background)
        self.root.option_add("*selectBackground", accent)
        self.root.option_add("*selectForeground", "#FFFFFF")
        self.root.option_add("*TCombobox*Listbox.background", colors["field"])
        self.root.option_add("*TCombobox*Listbox.foreground", text)
        self.root.option_add("*TCombobox*Listbox.selectBackground", accent)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
        style = ttk.Style(self.root)
        self._style = style
        if "clam" in style.theme_names() and style.theme_use() != "clam":
            style.theme_use("clam")
        style.configure(
            ".",
            background=background,
            foreground=text,
            font=("Segoe UI", 10),
        )
        style.configure("App.TFrame", background=background)
        style.configure("Page.TFrame", background=page)
        style.configure("Card.TFrame", background=card)
        style.configure(
            "Title.TLabel",
            background=background,
            foreground=text,
            font=("Segoe UI Semibold", 19),
        )
        style.configure(
            "Subtitle.TLabel",
            background=background,
            foreground=muted,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Version.TLabel",
            background=background,
            foreground=muted,
            font=("Segoe UI Semibold", 10),
        )
        style.configure("Hint.TLabel", background=background, foreground=muted)
        style.configure(
            "Logo.TLabel",
            background=accent,
            foreground="#FFFFFF",
            font=("Segoe UI Symbol", 19),
            padding=(12, 8),
        )
        style.configure("Status.TFrame", background=colors["status"])
        style.configure(
            "Status.TLabel",
            background=colors["status"],
            foreground=text,
            font=("Segoe UI", 10),
        )
        for state, color in (
            ("Info", accent),
            ("Pending", colors["warning"]),
            ("Success", colors["success"]),
            ("Warning", colors["warning"]),
            ("Error", colors["error"]),
        ):
            style.configure(
                f"{state}.StatusIcon.TLabel",
                background=colors["status"],
                foreground=color,
                font=("Segoe UI Symbol", 12),
            )
        style.configure("Card.TLabel", background=card, foreground=text)
        style.configure("Muted.Card.TLabel", background=card, foreground=muted)
        indicator = self._ensure_checkbox_indicator(style, theme, colors)
        checkbutton_layout: Any = [
            (
                "Checkbutton.padding",
                {
                    "sticky": "nswe",
                    "children": [
                        (indicator, {"side": "left", "sticky": ""}),
                        (
                            "Checkbutton.focus",
                            {
                                "side": "left",
                                "sticky": "w",
                                "children": [
                                    ("Checkbutton.label", {"sticky": "nswe"})
                                ],
                            },
                        ),
                    ],
                },
            )
        ]
        style.layout("Card.TCheckbutton", checkbutton_layout)
        style.configure(
            "Card.TCheckbutton",
            background=card,
            foreground=text,
            padding=(0, 4),
        )
        style.map(
            "Card.TCheckbutton",
            background=[("active", card)],
            foreground=[("disabled", colors["disabled"])],
        )
        style.layout("Header.TCheckbutton", checkbutton_layout)
        style.configure(
            "Header.TCheckbutton",
            background=background,
            foreground=muted,
            padding=(0, 4),
        )
        style.map(
            "Header.TCheckbutton",
            background=[("active", background)],
            foreground=[("active", text), ("disabled", colors["disabled"])],
        )
        style.configure(
            "Card.TLabelframe",
            background=card,
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "Card.TLabelframe.Label",
            background=card,
            foreground=text,
            font=("Segoe UI Semibold", 11),
            padding=(2, 0, 8, 0),
        )
        style.configure(
            "TEntry",
            background=colors["field"],
            fieldbackground=colors["field"],
            foreground=text,
            insertcolor=text,
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
            borderwidth=1,
            relief="solid",
            padding=(10, 8),
        )
        style.map(
            "TEntry",
            fieldbackground=[
                ("disabled", colors["field_disabled"]),
                ("readonly", colors["field_disabled"]),
            ],
            foreground=[("disabled", colors["disabled"])],
            bordercolor=[("focus", accent), ("disabled", border)],
            lightcolor=[("focus", accent)],
            darkcolor=[("focus", accent)],
        )
        style.configure(
            "TCombobox",
            background=colors["field"],
            fieldbackground=colors["field"],
            foreground=text,
            arrowcolor=muted,
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
            borderwidth=1,
            relief="solid",
            padding=(10, 7),
        )
        style.map(
            "TCombobox",
            background=[
                ("readonly", colors["field"]),
                ("active", colors["button_hover"]),
            ],
            fieldbackground=[
                ("readonly", colors["field"]),
                ("disabled", colors["field_disabled"]),
            ],
            foreground=[
                ("readonly", text),
                ("disabled", colors["disabled"]),
            ],
            arrowcolor=[("active", text), ("disabled", colors["disabled"])],
            bordercolor=[("focus", accent), ("active", accent)],
            lightcolor=[("focus", accent)],
            darkcolor=[("focus", accent)],
        )
        style.configure(
            "TButton",
            background=colors["button"],
            foreground=text,
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
            borderwidth=1,
            relief="solid",
            padding=(14, 9),
            focusthickness=1,
            focuscolor=accent,
        )
        style.map(
            "TButton",
            background=[
                ("disabled", colors["field_disabled"]),
                ("pressed", colors["accent_pressed"]),
                ("active", colors["button_hover"]),
            ],
            foreground=[("disabled", colors["disabled"])],
            bordercolor=[("focus", accent), ("active", accent)],
        )
        style.configure("Select.TButton", padding=(12, 8))
        style.configure(
            "Vertical.TScrollbar",
            background=colors["button"],
            troughcolor=page,
            bordercolor=page,
            lightcolor=colors["button"],
            darkcolor=colors["button"],
            arrowcolor=muted,
            gripcount=0,
        )
        style.map(
            "Vertical.TScrollbar",
            background=[("active", colors["button_hover"])],
            arrowcolor=[("active", text)],
        )
        segment_layout: Any = [
            (
                "Button.border",
                {
                    "sticky": "nswe",
                    "border": "1",
                    "children": [
                        (
                            "Radiobutton.padding",
                            {
                                "sticky": "nswe",
                                "children": [
                                    (
                                        "Radiobutton.focus",
                                        {
                                            "sticky": "nswe",
                                            "children": [
                                                (
                                                    "Radiobutton.label",
                                                    {"sticky": "nswe"},
                                                )
                                            ],
                                        },
                                    )
                                ],
                            },
                        )
                    ],
                },
            )
        ]
        style.layout("Segment.TRadiobutton", segment_layout)
        style.configure(
            "Segment.TRadiobutton",
            background=colors["button"],
            foreground=muted,
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
            borderwidth=1,
            relief="solid",
            padding=(12, 8),
            anchor="center",
            focusthickness=1,
            focuscolor=accent,
        )
        style.map(
            "Segment.TRadiobutton",
            background=[
                ("selected", accent),
                ("pressed", colors["accent_pressed"]),
                ("active", colors["button_hover"]),
            ],
            foreground=[("selected", "#FFFFFF"), ("active", text)],
            bordercolor=[("selected", accent), ("focus", accent)],
        )
        style.configure(
            "Accent.TButton",
            background=accent,
            foreground="#FFFFFF",
            bordercolor=accent,
            lightcolor=accent,
            darkcolor=accent,
            padding=(16, 9),
            focusthickness=1,
            focuscolor=accent,
        )
        style.map(
            "Accent.TButton",
            background=[
                ("disabled", colors["field_disabled"]),
                ("pressed", colors["accent_pressed"]),
                ("active", colors["accent_hover"]),
            ],
            foreground=[("disabled", colors["disabled"])],
            bordercolor=[
                ("pressed", colors["accent_pressed"]),
                ("active", colors["accent_hover"]),
            ],
        )
        style.configure(
            "App.TNotebook",
            background=page,
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
            borderwidth=1,
            tabmargins=(0, 0, 0, 0),
        )
        style.configure(
            "App.TNotebook.Tab",
            padding=(18, 10),
            background=colors["tab"],
            foreground=muted,
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "App.TNotebook.Tab",
            background=[
                ("selected", page),
                ("active", colors["button_hover"]),
            ],
            foreground=[("selected", text), ("active", text)],
        )
        self.root.after_idle(self._apply_windows_titlebar)

    def _ensure_checkbox_indicator(
        self,
        style: ttk.Style,
        theme: str,
        colors: dict[str, str],
    ) -> str:
        element = f"{theme.title()}.Checkbutton.indicator"
        if theme in self._indicator_images:
            return element
        unchecked = _checkbox_image(
            self.root,
            fill=colors["field"],
            border=colors["border"],
        )
        checked = _checkbox_image(
            self.root,
            fill=colors["accent"],
            border=colors["accent"],
            mark="#FFFFFF",
        )
        disabled = _checkbox_image(
            self.root,
            fill=colors["field_disabled"],
            border=colors["border"],
        )
        disabled_checked = _checkbox_image(
            self.root,
            fill=colors["field_disabled"],
            border=colors["border"],
            mark=colors["disabled"],
        )
        self._indicator_images[theme] = (
            unchecked,
            checked,
            disabled,
            disabled_checked,
        )
        style.element_create(
            element,
            "image",
            unchecked,
            ("disabled", "selected", disabled_checked),
            ("disabled", disabled),
            ("selected", checked),
            width=18,
            sticky="",
        )
        return element

    def _apply_windows_titlebar(self) -> None:
        if os.name != "nt":
            return
        try:
            window_id = self.root.winfo_id()
            get_parent = ctypes.windll.user32.GetParent
            get_parent.argtypes = [ctypes.c_void_p]
            get_parent.restype = ctypes.c_void_p
            parent_id = get_parent(ctypes.c_void_p(window_id))
            handle = ctypes.c_void_p(parent_id or window_id)
            enabled = ctypes.c_int(1 if self.dark_mode.get() else 0)
            set_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
            set_attribute.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.c_void_p,
                ctypes.c_uint,
            ]
            set_attribute.restype = ctypes.c_long
            for attribute in (20, 19):
                result = set_attribute(
                    handle,
                    attribute,
                    ctypes.byref(enabled),
                    ctypes.sizeof(enabled),
                )
                if result == 0:
                    break
        except (AttributeError, OSError, tk.TclError):
            log.debug("Не удалось обновить тему заголовка окна", exc_info=True)

    def _update_notification_controls(self) -> None:
        state = "normal" if self.notifications_enabled.get() else "disabled"
        self._notification_sound_checkbox.configure(state=state)

    def _set_status(self, message: str, state: str = "info") -> None:
        self.status.set(message)
        self._status_state = state
        self._refresh_status_indicator()

    def _refresh_status_indicator(self) -> None:
        indicator = getattr(self, "_status_indicator", None)
        if indicator is None:
            return
        state = self._status_state.title()
        indicator.configure(style=f"{state}.StatusIcon.TLabel")

    def _update_secret_visibility(self) -> None:
        show = "" if self.show_api_credentials.get() else "•"
        self._lastfm_api_key_entry.configure(show=show)
        self._telegram_api_hash_entry.configure(show=show)
        self._telegram_phone_entry.configure(show=show)

    def _update_output_controls(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        output_mode = self.telegram_output_mode.get()
        channel_mode = output_mode in {"personal_channel", "profile_and_channel"}
        profile_mode = output_mode in {"profile_music", "profile_and_channel"}
        channel_state = "normal" if channel_mode else "disabled"
        profile_state = "normal" if profile_mode else "disabled"
        self._personal_channel_entry.configure(state=channel_state)
        self._personal_channel_button.configure(state=channel_state)
        self._cache_size_entry.configure(state="normal")
        self._remove_when_idle_checkbox.configure(state=profile_state)
        self._update_emoji_controls()

    def _update_emoji_controls(self) -> None:
        state = (
            "normal" if self.telegram_playing_emoji_enabled.get() else "disabled"
        )
        self._playing_emoji_entry.configure(state=state)
        self._playing_emoji_button.configure(state=state)

    @staticmethod
    def _entry(
        parent: ttk.LabelFrame | ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        *,
        show: str | None = None,
    ) -> ttk.Entry:
        ttk.Label(parent, text=label, style="Card.TLabel").grid(
            row=row, column=0, sticky="w", padx=(0, 14), pady=5
        )
        entry = ttk.Entry(parent, textvariable=variable, width=42)
        if show is not None:
            entry.configure(show=show)
        entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=5)
        parent.columnconfigure(1, weight=1)
        return entry

    def _config_from_form(self) -> AppConfig:
        try:
            config = AppConfig(
                lastfm_username=self.lastfm_username.get().strip(),
                lastfm_api_key=self.lastfm_api_key.get().strip(),
                telegram_api_id=int(self.telegram_api_id.get().strip()),
                telegram_api_hash=self.telegram_api_hash.get().strip(),
                telegram_phone=self.telegram_phone.get().strip(),
                poll_interval_seconds=float(self.poll_interval.get().strip()),
                absent_confirmations=int(self.absent_confirmations.get().strip()),
                cache_size=int(self.cache_size.get().strip()),
                audio_mode=self.audio_mode.get(),
                download_workers=int(self.download_workers.get().strip()),
                remove_when_idle=self.remove_when_idle.get(),
                telegram_output_mode=self.telegram_output_mode.get(),
                telegram_personal_channel_id=int(
                    self.telegram_personal_channel_id.get().strip() or "0"
                ),
                telegram_playing_emoji_enabled=(
                    self.telegram_playing_emoji_enabled.get()
                ),
                telegram_playing_emoji_id=int(
                    self.telegram_playing_emoji_id.get().strip() or "0"
                ),
                notifications_enabled=self.notifications_enabled.get(),
                notification_sound_enabled=self.notification_sound_enabled.get(),
                ui_language=self.ui_language.get(),
                ui_theme="dark" if self.dark_mode.get() else "light",
            )
        except ValueError as exc:
            raise ConfigurationError(self._t("setup.numeric_invalid")) from exc
        config.validate()
        return config

    def _telegram_api_credentials(self) -> tuple[int, str]:
        try:
            api_id = int(self.telegram_api_id.get().strip())
        except ValueError as exc:
            raise ConfigurationError(self._t("setup.api_id_number")) from exc
        api_hash = self.telegram_api_hash.get().strip()
        if not api_id or not api_hash:
            raise ConfigurationError(self._t("setup.api_credentials_required"))
        return api_id, api_hash

    def _telegram_credentials(self) -> tuple[int, str, str]:
        api_id, api_hash = self._telegram_api_credentials()
        phone = self.telegram_phone.get().strip()
        if not phone:
            raise ConfigurationError(self._t("setup.phone_required"))
        return api_id, api_hash, phone

    def _test_lastfm(self) -> None:
        username = self.lastfm_username.get().strip()
        api_key = self.lastfm_api_key.get().strip()
        if not username or not api_key:
            messagebox.showerror(
                "Last.fm",
                self._t("lastfm.credentials_required"),
            )
            return
        self._set_status(self._t("lastfm.checking"), "pending")
        self.root.update_idletasks()
        try:
            with LastFmClient(
                api_key,
                username,
                language=self.ui_language.get(),
            ) as client:
                user = client.get_user()
                track = client.get_now_playing()
        except LastFmError as exc:
            self._set_status(self._t("lastfm.error", error=exc), "error")
            messagebox.showerror("Last.fm", str(exc))
            return
        self.lastfm_username.set(user.username)
        if track is None:
            result = self._t(
                "lastfm.connected_idle",
                username=user.username,
            )
        else:
            result = self._t(
                "lastfm.connected_track",
                username=user.username,
                track=track.display_name,
            )
        self._set_status(result, "success")
        messagebox.showinfo("Last.fm", result)
        self._save_draft()

    def _check_telegram_session(self) -> None:
        try:
            api_id, api_hash = self._telegram_api_credentials()
        except ConfigurationError:
            return
        try:
            authorized = _run_async(
                _telegram_is_authorized(self.session_path, api_id, api_hash)
            )
        except Exception:  # noqa: BLE001 - optional startup probe must not block UI
            return
        if authorized:
            self._set_status(self._t("telegram.session_authorized"), "success")

    def _send_telegram_code(self) -> None:
        try:
            api_id, api_hash, phone = self._telegram_credentials()
            self._save_draft()
            self.session_path.parent.mkdir(parents=True, exist_ok=True)
            self._set_status(self._t("telegram.sending_code"), "pending")
            self.root.update_idletasks()
            result = _run_async(
                _telegram_send_code(self.session_path, api_id, api_hash, phone)
            )
        except (ConfigurationError, ApiIdInvalidError, PhoneNumberInvalidError) as exc:
            messagebox.showerror("Telegram", str(exc))
            self._set_status(self._t("telegram.error", error=exc), "error")
            return
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports library errors
            messagebox.showerror("Telegram", str(exc))
            self._set_status(self._t("telegram.error", error=exc), "error")
            return
        if result is None:
            self._set_status(self._t("telegram.already_authorized"), "success")
        else:
            self._phone_code_hash = result
            self._set_status(self._t("telegram.code_sent"), "success")

    def _sign_in_telegram(self) -> None:
        try:
            api_id, api_hash, phone = self._telegram_credentials()
            code = self.telegram_code.get().strip().replace(" ", "")
            password = self.telegram_password.get()
            if not code:
                raise ConfigurationError(self._t("telegram.code_required"))
            self._set_status(self._t("telegram.authorizing"), "pending")
            self.root.update_idletasks()
            needs_password = _run_async(
                _telegram_sign_in(
                    self.session_path,
                    api_id,
                    api_hash,
                    phone,
                    code,
                    self._phone_code_hash,
                    password,
                    self._prompt_telegram_password,
                )
            )
        except (
            ConfigurationError,
            PhoneCodeInvalidError,
            PhoneCodeExpiredError,
            ApiIdInvalidError,
        ) as exc:
            messagebox.showerror("Telegram", str(exc))
            self._set_status(self._t("telegram.error", error=exc), "error")
            return
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports library errors
            messagebox.showerror("Telegram", str(exc))
            self._set_status(self._t("telegram.error", error=exc), "error")
            return

        if needs_password:
            self._set_status(self._t("telegram.2fa_cancelled"), "warning")
            messagebox.showwarning(
                "Telegram 2FA",
                self._t("telegram.2fa_retry"),
            )
        else:
            self.telegram_password.set("")
            self._set_status(self._t("telegram.authorized"), "success")

    def _prompt_telegram_password(self) -> str | None:
        return simpledialog.askstring(
            "Telegram 2FA",
            self._t("telegram.2fa_prompt"),
            show="•",
            parent=self.root,
        )

    def _select_playing_emoji(self) -> None:
        try:
            api_id, api_hash = self._telegram_api_credentials()
            self._set_status(self._t("emoji.selecting"), "pending")
            self.root.update_idletasks()
            document_id = _run_async(
                _telegram_capture_playing_emoji(
                    self.session_path,
                    api_id,
                    api_hash,
                    self._prompt_playing_emoji_selection,
                    language=self.ui_language.get(),
                )
            )
        except (ConfigurationError, TelegramError) as exc:
            messagebox.showerror("Telegram emoji status", str(exc))
            self._set_status(self._t("emoji.error", error=exc), "error")
            return
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports library errors
            messagebox.showerror("Telegram emoji status", str(exc))
            self._set_status(self._t("emoji.error", error=exc), "error")
            return

        if document_id is None:
            self._set_status(self._t("emoji.cancelled"), "warning")
            return
        self.telegram_playing_emoji_id.set(str(document_id))
        self._set_status(self._t("emoji.selected"), "success")
        self._save_draft()

    def _prompt_playing_emoji_selection(self) -> bool:
        return messagebox.askokcancel(
            self._t("emoji.dialog_title"),
            self._t("emoji.dialog"),
            parent=self.root,
        )

    def _select_personal_channel(self) -> None:
        try:
            api_id, api_hash = self._telegram_api_credentials()
            self._set_status(self._t("channel.selecting"), "pending")
            self.root.update_idletasks()
            selected = _run_async(
                _telegram_capture_personal_channel(
                    self.session_path,
                    api_id,
                    api_hash,
                    self._prompt_personal_channel_selection,
                    language=self.ui_language.get(),
                )
            )
        except (ConfigurationError, TelegramError) as exc:
            messagebox.showerror(self._t("channel.dialog_title"), str(exc))
            self._set_status(self._t("channel.error", error=exc), "error")
            return
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports library errors
            messagebox.showerror(self._t("channel.dialog_title"), str(exc))
            self._set_status(self._t("channel.error", error=exc), "error")
            return

        if selected is None:
            self._set_status(self._t("channel.cancelled"), "warning")
            return
        channel_id, title = selected
        self.telegram_personal_channel_id.set(str(channel_id))
        self._set_status(self._t("channel.selected", title=title), "success")
        self._save_draft()

    def _prompt_personal_channel_selection(self) -> bool:
        return messagebox.askokcancel(
            self._t("channel.dialog_title"),
            self._t("channel.dialog"),
            parent=self.root,
        )

    def _save(self) -> None:
        self._set_status(self._t("setup.saving"), "pending")
        self.root.update_idletasks()
        if not self._persist_config(show_errors=True):
            return
        self.saved = True
        self.root.destroy()

    def _persist_config(self, *, show_errors: bool) -> bool:
        try:
            config = self._config_from_form()
            config.save(self.config_path)
            default_draft_config_path().unlink(missing_ok=True)
        except (ConfigurationError, OSError) as exc:
            if show_errors:
                messagebox.showerror(self._t("setup.title"), str(exc))
                self._set_status(self._t("setup.save_error", error=exc), "error")
            return False
        log.info(
            "Настройки сохранены: audio_mode=%s, cache_size=%d, "
            "download_workers=%d, remove_when_idle=%s, output_mode=%s, "
            "personal_channel=%s, emoji_status=%s, "
            "notifications=%s, notification_sound=%s, ui_language=%s, ui_theme=%s",
            config.audio_mode,
            config.cache_size,
            config.download_workers,
            config.remove_when_idle,
            config.telegram_output_mode,
            config.telegram_personal_channel_id or None,
            (
                config.telegram_playing_emoji_id
                if config.telegram_playing_emoji_enabled
                else None
            ),
            config.notifications_enabled,
            config.notification_sound_enabled,
            config.ui_language,
            config.ui_theme,
        )
        return True

    def _save_draft(self) -> None:
        try:
            self._config_from_form().save(default_draft_config_path())
        except (ConfigurationError, OSError):
            return

    def _open_api_page(self) -> None:
        webbrowser.open(LASTFM_API_ACCOUNT_URL)

    def _open_scrobbler(self) -> None:
        webbrowser.open(WEB_SCROBBLER_URL)

    def _close(self) -> None:
        if self._persist_config(show_errors=False):
            self.saved = True
        else:
            self._save_draft()
        self.root.destroy()

    def _cancel(self) -> None:
        self.root.destroy()


def _checkbox_image(
    master: tk.Misc,
    *,
    fill: str,
    border: str,
    mark: str | None = None,
) -> tk.PhotoImage:
    image = tk.PhotoImage(master=master, width=18, height=18)
    image.put(border, to=(1, 1, 17, 17))
    image.put(fill, to=(2, 2, 16, 16))
    if mark is not None:
        points = (
            (4, 9),
            (5, 10),
            (6, 11),
            (7, 12),
            (8, 11),
            (9, 10),
            (10, 9),
            (11, 8),
            (12, 7),
            (13, 6),
            (14, 5),
        )
        for x, y in points:
            image.put(mark, to=(x, y, x + 2, y + 2))
    return image


def _mix_color(start: str, end: str, ratio: float) -> str:
    try:
        start_rgb = tuple(int(start[index : index + 2], 16) for index in (1, 3, 5))
        end_rgb = tuple(int(end[index : index + 2], 16) for index in (1, 3, 5))
    except (TypeError, ValueError):
        return end
    mixed = tuple(
        round(source + (target - source) * ratio)
        for source, target in zip(start_rgb, end_rgb, strict=True)
    )
    return "#{:02X}{:02X}{:02X}".format(*mixed)


def run_setup(config_path: Path | None = None) -> bool:
    return SetupWizard(config_path).run()


def _run_async(coroutine):
    return asyncio.run(coroutine)


async def _telegram_is_authorized(
    session_path: Path, api_id: int, api_hash: str
) -> bool:
    client = TelegramClient(str(session_path), api_id, api_hash)
    try:
        await client.connect()
        return await client.is_user_authorized()
    finally:
        await client.disconnect()


async def _telegram_send_code(
    session_path: Path, api_id: int, api_hash: str, phone: str
) -> str | None:
    client = TelegramClient(str(session_path), api_id, api_hash)
    try:
        await client.connect()
        if await client.is_user_authorized():
            return None
        sent = await client.send_code_request(phone)
        return sent.phone_code_hash
    finally:
        await client.disconnect()


async def _telegram_sign_in(
    session_path: Path,
    api_id: int,
    api_hash: str,
    phone: str,
    code: str,
    phone_code_hash: str | None,
    password: str,
    password_provider: Callable[[], str | None] | None = None,
) -> bool:
    client = TelegramClient(str(session_path), api_id, api_hash)
    try:
        await client.connect()
        if await client.is_user_authorized():
            return False
        try:
            await client.sign_in(
                phone=phone,
                code=code,
                phone_code_hash=phone_code_hash,
            )
        except SessionPasswordNeededError:
            resolved_password = password
            if not resolved_password and password_provider is not None:
                resolved_password = password_provider() or ""
            if not resolved_password:
                return True
            await client.sign_in(password=resolved_password)
        return False
    finally:
        await client.disconnect()


async def _telegram_capture_playing_emoji(
    session_path: Path,
    api_id: int,
    api_hash: str,
    selection_prompt: Callable[[], bool],
    *,
    language: str = "ru",
) -> int | None:
    client = TelegramClient(str(session_path), api_id, api_hash)
    original_status = None
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise ConfigurationError(
                translate("emoji.telegram_unauthorized", language)
            )
        user = await client.get_me()
        if user is None:
            raise ConfigurationError(translate("emoji.no_user", language))
        if not getattr(user, "premium", False):
            raise ConfigurationError(
                translate("emoji.premium_required", language)
            )
        original_status = _emoji_status_for_update(
            getattr(user, "emoji_status", None),
            language=language,
        )

        if not selection_prompt():
            return None
        selected_user = await client.get_me()
        selected_status = getattr(selected_user, "emoji_status", None)
        if isinstance(selected_status, types.EmojiStatusCollectible):
            raise ConfigurationError(
                translate("emoji.collectible", language)
            )
        if not isinstance(selected_status, types.EmojiStatus):
            raise ConfigurationError(translate("emoji.not_selected", language))
        return int(selected_status.document_id)
    finally:
        try:
            if original_status is not None:
                restored = await client(
                    functions.account.UpdateEmojiStatusRequest(original_status)
                )
                if restored is False:
                    raise TelegramError(
                        translate("emoji.restore_rejected", language)
                    )
        finally:
            await client.disconnect()


async def _telegram_capture_personal_channel(
    session_path: Path,
    api_id: int,
    api_hash: str,
    selection_prompt: Callable[[], bool],
    *,
    language: str = "ru",
) -> tuple[int, str] | None:
    client = TelegramClient(str(session_path), api_id, api_hash)
    original_channel = None
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise ConfigurationError(
                translate("channel.telegram_unauthorized", language)
            )
        original_result = await client(functions.users.GetFullUserRequest("me"))
        original_full_user = getattr(original_result, "full_user", None)
        if original_full_user is None:
            raise ConfigurationError(translate("channel.no_user", language))
        original_id = int(
            getattr(original_full_user, "personal_channel_id", 0) or 0
        )
        original_channel = types.InputChannelEmpty()
        if original_id:
            original_channels = await _telegram_personal_channels(client)
            original_entity = original_channels.get(original_id)
            if original_entity is None:
                raise ConfigurationError(
                    translate("channel.original_unavailable", language)
                )
            original_channel = utils.get_input_channel(original_entity)

        if not selection_prompt():
            return None

        selected_result = await client(functions.users.GetFullUserRequest("me"))
        selected_full_user = getattr(selected_result, "full_user", None)
        if selected_full_user is None:
            raise ConfigurationError(translate("channel.no_user", language))
        selected_id = int(
            getattr(selected_full_user, "personal_channel_id", 0) or 0
        )
        if not selected_id:
            raise ConfigurationError(translate("channel.not_selected", language))
        selected_channels = await _telegram_personal_channels(client)
        selected_channel = selected_channels.get(selected_id)
        if selected_channel is None:
            raise ConfigurationError(translate("channel.unavailable", language))
        return selected_id, str(getattr(selected_channel, "title", selected_id))
    finally:
        try:
            if original_channel is not None:
                restored = await client(
                    functions.account.UpdatePersonalChannelRequest(original_channel)
                )
                if restored is False:
                    raise TelegramError(
                        translate("channel.restore_rejected", language)
                    )
        finally:
            await client.disconnect()


async def _telegram_personal_channels(client: TelegramClient) -> dict[int, Any]:
    result = await client(
        functions.channels.GetAdminedPublicChannelsRequest(for_personal=True)
    )
    return {
        int(channel.id): channel
        for channel in getattr(result, "chats", [])
        if isinstance(channel, types.Channel)
    }
