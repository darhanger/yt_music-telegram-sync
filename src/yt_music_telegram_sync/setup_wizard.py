from __future__ import annotations

import asyncio
import logging
import tkinter as tk
import webbrowser
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from telethon import TelegramClient
from telethon.errors import (
    ApiIdInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

from .config import (
    AppConfig,
    ConfigurationError,
    default_config_path,
    default_draft_config_path,
    default_session_path,
    load_partial,
)
from .lastfm import LastFmClient, LastFmError

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
        self.root.title("YT Music → Telegram: настройка")
        self.root.geometry("720x720")
        self.root.minsize(680, 660)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.saved = False
        self._phone_code_hash: str | None = None

        self.lastfm_username = tk.StringVar(value=config.lastfm_username)
        self.lastfm_api_key = tk.StringVar(value=config.lastfm_api_key)
        self.telegram_api_id = tk.StringVar(
            value=str(config.telegram_api_id) if config.telegram_api_id else ""
        )
        self.telegram_api_hash = tk.StringVar(value=config.telegram_api_hash)
        self.telegram_phone = tk.StringVar(value=config.telegram_phone)
        self.telegram_code = tk.StringVar()
        self.telegram_password = tk.StringVar()
        self.poll_interval = tk.StringVar(value=str(config.poll_interval_seconds))
        self.absent_confirmations = tk.StringVar(value=str(config.absent_confirmations))
        self.cache_size = tk.StringVar(value=str(config.cache_size))
        self.audio_mode = tk.StringVar(value=config.audio_mode)
        self.download_workers = tk.StringVar(value=str(config.download_workers))
        self.remove_when_idle = tk.BooleanVar(value=config.remove_when_idle)
        self.status = tk.StringVar(value="Заполните параметры и проверьте подключения")

        self._build()
        self.root.after(150, self._check_telegram_session)

    def run(self) -> bool:
        self.root.mainloop()
        return self.saved

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill=tk.BOTH, expand=True)

        lastfm = ttk.LabelFrame(outer, text="Last.fm", padding=12)
        lastfm.pack(fill=tk.X)
        self._entry(lastfm, 0, "Имя пользователя", self.lastfm_username)
        self._entry(lastfm, 1, "API key", self.lastfm_api_key, show="")
        note = ttk.Label(
            lastfm,
            text=(
                "Пароль здесь не вводится: для чтения nowplaying Last.fm требует только "
                "username и API key. В Web Scrobbler вход выполняется на странице Last.fm."
            ),
            wraplength=620,
            foreground="#555555",
        )
        note.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 4))
        buttons = ttk.Frame(lastfm)
        buttons.grid(row=3, column=0, columnspan=3, sticky="w")
        ttk.Button(buttons, text="Получить API key", command=self._open_api_page).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(buttons, text="Web Scrobbler", command=self._open_scrobbler).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(buttons, text="Проверить Last.fm", command=self._test_lastfm).pack(
            side=tk.LEFT
        )

        telegram = ttk.LabelFrame(outer, text="Telegram", padding=12)
        telegram.pack(fill=tk.X, pady=(12, 0))
        self._entry(telegram, 0, "API ID", self.telegram_api_id)
        self._entry(telegram, 1, "API hash", self.telegram_api_hash)
        self._entry(telegram, 2, "Телефон", self.telegram_phone)
        ttk.Button(
            telegram, text="1. Отправить код", command=self._send_telegram_code
        ).grid(row=3, column=0, sticky="w", pady=(8, 2))
        self._entry(telegram, 4, "Код из Telegram", self.telegram_code)
        self._entry(
            telegram,
            5,
            "Пароль Telegram 2FA",
            self.telegram_password,
            show="•",
        )
        ttk.Button(
            telegram, text="2. Войти в Telegram", command=self._sign_in_telegram
        ).grid(row=6, column=0, sticky="w", pady=(8, 2))
        ttk.Label(
            telegram,
            text="Пароль 2FA используется только при входе и не сохраняется.",
            foreground="#555555",
        ).grid(row=6, column=1, columnspan=2, sticky="w", padx=(8, 0))

        behavior = ttk.LabelFrame(outer, text="Синхронизация", padding=12)
        behavior.pack(fill=tk.X, pady=(12, 0))
        self._entry(behavior, 0, "Опрос Last.fm, секунд", self.poll_interval)
        self._entry(behavior, 1, "Проверок перед idle", self.absent_confirmations)
        self._entry(behavior, 2, "Треков в профиле", self.cache_size)
        ttk.Label(behavior, text="Режим аудио").grid(
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
        self._entry(behavior, 4, "Параллельных загрузок", self.download_workers)
        ttk.Checkbutton(
            behavior,
            text="Удалять музыку профиля, когда nowplaying исчез",
            variable=self.remove_when_idle,
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))

        ttk.Label(outer, textvariable=self.status, wraplength=650).pack(
            fill=tk.X, pady=(14, 8)
        )
        footer = ttk.Frame(outer)
        footer.pack(fill=tk.X)
        ttk.Button(footer, text="Сохранить", command=self._save).pack(side=tk.RIGHT)
        ttk.Button(footer, text="Отмена", command=self._cancel).pack(
            side=tk.RIGHT, padx=(0, 8)
        )

    @staticmethod
    def _entry(
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        variable: tk.StringVar,
        *,
        show: str | None = None,
    ) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(
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
            )
        except ValueError as exc:
            raise ConfigurationError(
                "Числовые параметры заполнены некорректно"
            ) from exc
        config.validate()
        return config

    def _telegram_credentials(self) -> tuple[int, str, str]:
        try:
            api_id = int(self.telegram_api_id.get().strip())
        except ValueError as exc:
            raise ConfigurationError("Telegram API ID должен быть числом") from exc
        api_hash = self.telegram_api_hash.get().strip()
        phone = self.telegram_phone.get().strip()
        if not api_id or not api_hash or not phone:
            raise ConfigurationError("Заполните Telegram API ID, API hash и телефон")
        return api_id, api_hash, phone

    def _test_lastfm(self) -> None:
        username = self.lastfm_username.get().strip()
        api_key = self.lastfm_api_key.get().strip()
        if not username or not api_key:
            messagebox.showerror("Last.fm", "Введите username и API key")
            return
        self.status.set("Проверка Last.fm…")
        self.root.update_idletasks()
        try:
            with LastFmClient(api_key, username) as client:
                user = client.get_user()
                track = client.get_now_playing()
        except LastFmError as exc:
            self.status.set(f"Ошибка Last.fm: {exc}")
            messagebox.showerror("Last.fm", str(exc))
            return
        self.lastfm_username.set(user.username)
        if track is None:
            result = (
                f"Last.fm подключён: {user.username}. Активный nowplaying не найден."
            )
        else:
            result = f"Last.fm подключён: {user.username}. Сейчас играет: {track.display_name}"
        self.status.set(result)
        messagebox.showinfo("Last.fm", result)
        self._save_draft()

    def _check_telegram_session(self) -> None:
        try:
            api_id, api_hash, _ = self._telegram_credentials()
        except ConfigurationError:
            return
        try:
            authorized = _run_async(
                _telegram_is_authorized(self.session_path, api_id, api_hash)
            )
        except Exception:  # noqa: BLE001 - optional startup probe must not block UI
            return
        if authorized:
            self.status.set("Существующая Telegram-сессия авторизована")

    def _send_telegram_code(self) -> None:
        try:
            api_id, api_hash, phone = self._telegram_credentials()
            self._save_draft()
            self.session_path.parent.mkdir(parents=True, exist_ok=True)
            self.status.set("Отправка кода Telegram…")
            self.root.update_idletasks()
            result = _run_async(
                _telegram_send_code(self.session_path, api_id, api_hash, phone)
            )
        except (ConfigurationError, ApiIdInvalidError, PhoneNumberInvalidError) as exc:
            messagebox.showerror("Telegram", str(exc))
            self.status.set(f"Ошибка Telegram: {exc}")
            return
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports library errors
            messagebox.showerror("Telegram", str(exc))
            self.status.set(f"Ошибка Telegram: {exc}")
            return
        if result is None:
            self.status.set("Telegram уже авторизован. Нажмите «Сохранить» после изменений")
        else:
            self._phone_code_hash = result
            self.status.set("Код отправлен. Введите его и нажмите «Войти в Telegram»")

    def _sign_in_telegram(self) -> None:
        try:
            api_id, api_hash, phone = self._telegram_credentials()
            code = self.telegram_code.get().strip().replace(" ", "")
            password = self.telegram_password.get()
            if not code:
                raise ConfigurationError("Введите код из Telegram")
            self.status.set("Авторизация Telegram…")
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
            self.status.set(f"Ошибка Telegram: {exc}")
            return
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports library errors
            messagebox.showerror("Telegram", str(exc))
            self.status.set(f"Ошибка Telegram: {exc}")
            return

        if needs_password:
            self.status.set("Вход с 2FA отменён. Запросите новый код и повторите вход")
            messagebox.showwarning(
                "Telegram 2FA",
                "Для продолжения запросите новый код Telegram. При следующем входе "
                "введите пароль 2FA или укажите его во всплывающем окне.",
            )
        else:
            self.telegram_password.set("")
            self.status.set(
                "Telegram успешно авторизован. Проверьте параметры и нажмите «Сохранить»"
            )

    def _prompt_telegram_password(self) -> str | None:
        return simpledialog.askstring(
            "Telegram 2FA",
            "Введите пароль двухэтапной аутентификации Telegram.\n"
            "Он используется только сейчас и не сохраняется.",
            show="•",
            parent=self.root,
        )

    def _save(self) -> None:
        self.status.set("Сохранение настроек…")
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
                messagebox.showerror("Настройка", str(exc))
                self.status.set(f"Ошибка сохранения: {exc}")
            return False
        log.info(
            "Настройки сохранены: audio_mode=%s, cache_size=%d, "
            "download_workers=%d, remove_when_idle=%s",
            config.audio_mode,
            config.cache_size,
            config.download_workers,
            config.remove_when_idle,
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
