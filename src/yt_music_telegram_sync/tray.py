from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from subprocess import Popen

import pystray
from PIL import Image, ImageDraw

from . import __version__
from .config import default_log_path
from .localization import translate
from .service import ServiceStatus, SyncApplicationService

log = logging.getLogger(__name__)
_NIIF_NOSOUND = 0x00000010


class _NotificationIcon(pystray.Icon):
    def __init__(self, *args, sound_enabled: bool, **kwargs) -> None:
        self._sound_enabled = sound_enabled
        super().__init__(*args, **kwargs)

    def _notify(self, message: str, title: str | None = None) -> None:
        if os.name == "nt" and not self._sound_enabled:
            from pystray._util import win32

            self._message(
                win32.NIM_MODIFY,
                win32.NIF_INFO,
                szInfo=message,
                szInfoTitle=title or self.title or "",
                dwInfoFlags=_NIIF_NOSOUND,
            )
            return
        super()._notify(message, title)


class TrayController:
    def __init__(
        self,
        service: SyncApplicationService,
        *,
        config_path: Path,
    ) -> None:
        self.service = service
        self._config_path = config_path
        self._exit_lock = threading.Lock()
        self._setup_lock = threading.Lock()
        self._setup_process: Popen[bytes] | None = None
        self._exiting = False
        self._language = service.config.ui_language
        self._notifications_enabled = service.config.notifications_enabled
        self.icon = _NotificationIcon(
            "YTMusicTelegramSync",
            _create_icon(),
            f"YT Music → Telegram · v{__version__}",
            sound_enabled=service.config.notification_sound_enabled,
            menu=pystray.Menu(
                pystray.MenuItem(self._status_text, None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(self._pause_text, self._toggle_pause),
                pystray.MenuItem(self._t("tray.sync_now"), self._sync_now),
                pystray.MenuItem(self._t("tray.clear"), self._clear),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(self._t("tray.settings"), self._open_setup),
                pystray.MenuItem(self._t("tray.open_log"), self._open_log),
                pystray.MenuItem(self._t("tray.open_data"), self._open_data),
                pystray.MenuItem(self._t("tray.restart"), self._restart),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(self._t("tray.exit"), self._exit),
            ),
        )

    def _t(self, key: str, **values: object) -> str:
        return translate(key, getattr(self, "_language", "ru"), **values)

    def run(self) -> None:
        self.service.set_status_callback(self.on_status)
        self.service.start()
        self.icon.run()

    def on_status(self, status: ServiceStatus) -> None:
        self.icon.title = f"YT Music → Telegram\n{status.message}"[:127]
        try:
            self.icon.update_menu()
        except Exception:
            log.debug("Tray menu update failed", exc_info=True)
        if status.track is not None:
            self._notify(status.track.display_name, self._t("tray.synced"))
        elif status.kind == "error":
            self._notify(status.message, self._t("tray.sync_error"))
        elif status.kind == "idle" and status.message in {
            self._t("service.idle_cleaned"),
            self._t("service.profile_cleared"),
        }:
            self._notify(status.message, self._t("tray.cleanup_done"))

    def _status_text(self, _item: pystray.MenuItem) -> str:
        return self.service.status.message[:80]

    def _pause_text(self, _item: pystray.MenuItem) -> str:
        return (
            self._t("tray.resume")
            if self.service.is_paused
            else self._t("tray.pause")
        )

    def _toggle_pause(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self.service.toggle_pause()
        self.icon.update_menu()

    def _sync_now(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self.service.sync_now()

    def _clear(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self.service.clear_profile_music()

    def _open_setup(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        with self._setup_lock:
            if (
                self._setup_process is not None
                and self._setup_process.poll() is None
            ):
                self._notify(
                    self._t("tray.setup_open"),
                    self._t("tray.setup_title"),
                )
                return
        self.service.stop()
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "yt_music_telegram_sync",
                    "--setup",
                    "--config",
                    str(self._config_path),
                ],
                close_fds=True,
            )
        except OSError as exc:
            log.exception("Не удалось открыть настройки")
            self.service.start()
            self._notify(str(exc), self._t("tray.setup_open_error"))
            return
        with self._setup_lock:
            self._setup_process = process
        threading.Thread(
            target=self._finish_setup,
            args=(process,),
            name="setup-waiter",
            daemon=True,
        ).start()
        self._notify(
            self._t("tray.setup_restart"),
            self._t("tray.setup_title"),
        )

    def _open_log(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        path = default_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        _open_path(path)

    def _open_data(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        path = default_log_path().parent.parent
        path.mkdir(parents=True, exist_ok=True)
        _open_path(path)

    def _restart(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        with self._setup_lock:
            if (
                self._setup_process is not None
                and self._setup_process.poll() is None
            ):
                self._notify(
                    self._t("tray.restart_wait"),
                    self._t("tray.restart_wait_title"),
                )
                return
        self._restart_application()

    def _finish_setup(self, process: Popen[bytes]) -> None:
        return_code = process.wait()
        with self._setup_lock:
            if self._setup_process is process:
                self._setup_process = None
        if return_code == 0:
            self._restart_application()
            return
        self.service.start()
        self._notify(
            self._t("tray.setup_discarded"),
            self._t("tray.setup_closed"),
        )

    def _restart_application(self) -> None:
        self.service.stop()
        try:
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "yt_music_telegram_sync",
                    "--tray",
                    "--restart-wait",
                    "--config",
                    str(self._config_path),
                ],
                close_fds=True,
            )
        except OSError as exc:
            log.exception("Не удалось перезапустить приложение")
            self.service.start()
            self._notify(str(exc), self._t("tray.restart_error"))
            return
        self.icon.stop()

    def _exit(self, icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        with self._exit_lock:
            if self._exiting:
                return
            self._exiting = True
        self.service.stop()
        icon.stop()

    def _notify(self, message: str, title: str) -> None:
        if not self._notifications_enabled:
            return
        try:
            self.icon.notify(message, title)
        except Exception:
            log.debug("Tray notification failed", exc_info=True)


def _create_icon() -> Image.Image:
    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((2, 2, 62, 62), fill=(211, 47, 47, 255))
    draw.rounded_rectangle((31, 14, 38, 46), radius=3, fill="white")
    draw.polygon(((37, 14), (52, 18), (52, 25), (37, 21)), fill="white")
    draw.ellipse((19, 39, 38, 54), fill="white")
    return image


def _open_path(path: Path) -> None:
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)], close_fds=True)
