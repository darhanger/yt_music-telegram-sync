from __future__ import annotations

import asyncio
import logging
import tkinter as tk
import webbrowser
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from telethon import TelegramClient, functions, types
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
        self.root.geometry("780x740")
        self.root.minsize(720, 660)
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

        self._configure_style()
        self._build()
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
        self.status.set(self._t("status.language_changed"))
        self._outer.destroy()
        self._build()
        self._notebook.select(selected_tab)

    def _build(self) -> None:
        self.root.title(self._t("window.title", version=__version__))
        outer = ttk.Frame(
            self.root,
            padding=(24, 14, 24, 14),
            style="App.TFrame",
        )
        self._outer = outer
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        header = ttk.Frame(outer, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
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
        ).pack(side=tk.RIGHT, padx=(12, 0), pady=(7, 0))
        ttk.Label(
            header_actions,
            text=self._t("language.label"),
            style="Hint.TLabel",
        ).pack(side=tk.LEFT, padx=(0, 6), pady=(8, 0))
        language = ttk.Combobox(
            header_actions,
            textvariable=self.language_display,
            values=tuple(LANGUAGE_LABELS.values()),
            state="readonly",
            width=9,
        )
        language.pack(side=tk.LEFT, pady=(1, 0))
        language.bind("<<ComboboxSelected>>", self._change_language)

        notebook = ttk.Notebook(outer, style="App.TNotebook")
        self._notebook = notebook
        notebook.grid(row=1, column=0, sticky="nsew")
        lastfm_page = ttk.Frame(
            notebook,
            padding=(12, 14),
            style="Page.TFrame",
        )
        telegram_page = ttk.Frame(
            notebook,
            padding=(12, 14),
            style="Page.TFrame",
        )
        synchronization = ttk.Frame(
            notebook,
            padding=(12, 14),
            style="Page.TFrame",
        )
        notebook.add(lastfm_page, text="  Last.fm  ")
        notebook.add(telegram_page, text="  Telegram  ")
        notebook.add(synchronization, text=self._t("tabs.sync"))

        lastfm = ttk.LabelFrame(
            lastfm_page,
            text="Last.fm",
            padding=14,
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
            padding=14,
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
            padding=14,
            style="Card.TLabelframe",
        )
        behavior.pack(fill=tk.X)
        self._entry(behavior, 0, self._t("behavior.poll"), self.poll_interval)
        self._entry(behavior, 1, self._t("behavior.absent"), self.absent_confirmations)
        self._entry(behavior, 2, self._t("behavior.cache"), self.cache_size)
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
            width=24,
        )
        mode.grid(row=3, column=1, sticky="ew", pady=4)
        ttk.Label(
            behavior,
            text=self._t("behavior.emoji"),
            style="Card.TLabel",
        ).grid(
            row=4, column=0, sticky="w", padx=(0, 12), pady=4
        )
        ttk.Entry(
            behavior,
            textvariable=self.telegram_playing_emoji_id,
            width=28,
        ).grid(row=4, column=1, sticky="ew", pady=4)
        ttk.Button(
            behavior,
            text=self._t("behavior.select"),
            command=self._select_playing_emoji,
        ).grid(row=4, column=2, sticky="e", padx=(8, 0), pady=4)
        self._entry(
            behavior,
            5,
            self._t("behavior.workers"),
            self.download_workers,
        )
        ttk.Checkbutton(
            behavior,
            text=self._t("behavior.remove_idle"),
            variable=self.remove_when_idle,
            style="Card.TCheckbutton",
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))

        notifications = ttk.LabelFrame(
            synchronization,
            text=self._t("notifications.title"),
            padding=14,
            style="Card.TLabelframe",
        )
        notifications.pack(fill=tk.X, pady=(12, 0))
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

        ttk.Label(
            outer,
            textvariable=self.status,
            wraplength=680,
            style="Status.TLabel",
            padding=(12, 7),
        ).grid(row=2, column=0, sticky="ew", pady=(10, 6))
        footer = ttk.Frame(outer, style="App.TFrame")
        footer.grid(row=3, column=0, sticky="ew", pady=(0, 2))
        ttk.Label(
            footer,
            text=self._t("footer.hint"),
            style="Hint.TLabel",
        ).pack(side=tk.LEFT, pady=7)
        ttk.Button(
            footer,
            text=self._t("footer.save"),
            command=self._save,
            style="Accent.TButton",
        ).pack(side=tk.RIGHT)
        ttk.Button(
            footer,
            text=self._t("footer.cancel"),
            command=self._cancel,
        ).pack(
            side=tk.RIGHT, padx=(0, 8)
        )

    def _configure_style(self) -> None:
        background = "#f3f6fb"
        card = "#ffffff"
        text = "#172033"
        muted = "#657087"
        accent = "#2563eb"
        accent_active = "#1d4ed8"

        self.root.configure(background=background)
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10))
        style.configure("App.TFrame", background=background)
        style.configure("Page.TFrame", background=background)
        style.configure("Card.TFrame", background=card)
        style.configure("Title.TLabel", background=background, foreground=text, font=("Segoe UI Semibold", 18))
        style.configure("Subtitle.TLabel", background=background, foreground=muted)
        style.configure("Version.TLabel", background=background, foreground=muted, font=("Segoe UI Semibold", 10))
        style.configure("Hint.TLabel", background=background, foreground=muted)
        style.configure("Logo.TLabel", background=accent, foreground="#ffffff", font=("Segoe UI Symbol", 19), padding=(11, 7))
        style.configure("Status.TLabel", background="#e8f0ff", foreground="#1e3a66")
        style.configure("Card.TLabel", background=card, foreground=text)
        style.configure("Muted.Card.TLabel", background=card, foreground=muted)
        style.configure("Card.TCheckbutton", background=card, foreground=text)
        style.map("Card.TCheckbutton", background=[("active", card)])
        style.configure(
            "Card.TLabelframe",
            background=card,
            bordercolor="#dce3ee",
            relief="solid",
        )
        style.configure(
            "Card.TLabelframe.Label",
            background=card,
            foreground=text,
            font=("Segoe UI Semibold", 11),
        )
        style.configure("TEntry", padding=(7, 6), fieldbackground="#ffffff")
        style.configure("TCombobox", padding=(7, 5))
        style.configure("TButton", padding=(12, 8))
        style.configure(
            "Accent.TButton",
            background=accent,
            foreground="#ffffff",
            bordercolor=accent,
            focusthickness=2,
            focuscolor=accent,
        )
        style.map(
            "Accent.TButton",
            background=[("pressed", accent_active), ("active", accent_active)],
            bordercolor=[("pressed", accent_active), ("active", accent_active)],
        )
        style.configure("App.TNotebook", background=background, borderwidth=0)
        style.configure(
            "App.TNotebook.Tab",
            padding=(16, 9),
            background="#e7ebf2",
            foreground=muted,
        )
        style.map(
            "App.TNotebook.Tab",
            background=[("selected", card), ("active", "#eef2f8")],
            foreground=[("selected", text)],
        )

    def _update_notification_controls(self) -> None:
        state = "normal" if self.notifications_enabled.get() else "disabled"
        self._notification_sound_checkbox.configure(state=state)

    def _update_secret_visibility(self) -> None:
        show = "" if self.show_api_credentials.get() else "•"
        self._lastfm_api_key_entry.configure(show=show)
        self._telegram_api_hash_entry.configure(show=show)
        self._telegram_phone_entry.configure(show=show)

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
            row=row, column=0, sticky="w", padx=(0, 12), pady=4
        )
        entry = ttk.Entry(parent, textvariable=variable, width=42)
        if show is not None:
            entry.configure(show=show)
        entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)
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
                telegram_playing_emoji_id=int(
                    self.telegram_playing_emoji_id.get().strip() or "0"
                ),
                notifications_enabled=self.notifications_enabled.get(),
                notification_sound_enabled=self.notification_sound_enabled.get(),
                ui_language=self.ui_language.get(),
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
        self.status.set(self._t("lastfm.checking"))
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
            self.status.set(self._t("lastfm.error", error=exc))
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
        self.status.set(result)
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
            self.status.set(self._t("telegram.session_authorized"))

    def _send_telegram_code(self) -> None:
        try:
            api_id, api_hash, phone = self._telegram_credentials()
            self._save_draft()
            self.session_path.parent.mkdir(parents=True, exist_ok=True)
            self.status.set(self._t("telegram.sending_code"))
            self.root.update_idletasks()
            result = _run_async(
                _telegram_send_code(self.session_path, api_id, api_hash, phone)
            )
        except (ConfigurationError, ApiIdInvalidError, PhoneNumberInvalidError) as exc:
            messagebox.showerror("Telegram", str(exc))
            self.status.set(self._t("telegram.error", error=exc))
            return
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports library errors
            messagebox.showerror("Telegram", str(exc))
            self.status.set(self._t("telegram.error", error=exc))
            return
        if result is None:
            self.status.set(self._t("telegram.already_authorized"))
        else:
            self._phone_code_hash = result
            self.status.set(self._t("telegram.code_sent"))

    def _sign_in_telegram(self) -> None:
        try:
            api_id, api_hash, phone = self._telegram_credentials()
            code = self.telegram_code.get().strip().replace(" ", "")
            password = self.telegram_password.get()
            if not code:
                raise ConfigurationError(self._t("telegram.code_required"))
            self.status.set(self._t("telegram.authorizing"))
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
            self.status.set(self._t("telegram.error", error=exc))
            return
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports library errors
            messagebox.showerror("Telegram", str(exc))
            self.status.set(self._t("telegram.error", error=exc))
            return

        if needs_password:
            self.status.set(self._t("telegram.2fa_cancelled"))
            messagebox.showwarning(
                "Telegram 2FA",
                self._t("telegram.2fa_retry"),
            )
        else:
            self.telegram_password.set("")
            self.status.set(self._t("telegram.authorized"))

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
            self.status.set(self._t("emoji.selecting"))
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
            self.status.set(self._t("emoji.error", error=exc))
            return
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports library errors
            messagebox.showerror("Telegram emoji status", str(exc))
            self.status.set(self._t("emoji.error", error=exc))
            return

        if document_id is None:
            self.status.set(self._t("emoji.cancelled"))
            return
        self.telegram_playing_emoji_id.set(str(document_id))
        self.status.set(self._t("emoji.selected"))
        self._save_draft()

    def _prompt_playing_emoji_selection(self) -> bool:
        return messagebox.askokcancel(
            self._t("emoji.dialog_title"),
            self._t("emoji.dialog"),
            parent=self.root,
        )

    def _save(self) -> None:
        self.status.set(self._t("setup.saving"))
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
                self.status.set(self._t("setup.save_error", error=exc))
            return False
        log.info(
            "Настройки сохранены: audio_mode=%s, cache_size=%d, "
            "download_workers=%d, remove_when_idle=%s, emoji_status=%s, "
            "notifications=%s, notification_sound=%s, ui_language=%s",
            config.audio_mode,
            config.cache_size,
            config.download_workers,
            config.remove_when_idle,
            bool(config.telegram_playing_emoji_id),
            config.notifications_enabled,
            config.notification_sound_enabled,
            config.ui_language,
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
