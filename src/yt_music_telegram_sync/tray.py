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

from .config import default_log_path
from .service import ServiceStatus, SyncApplicationService

log = logging.getLogger(__name__)


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
        self.icon = pystray.Icon(
            "YTMusicTelegramSync",
            _create_icon(),
            "YT Music → Telegram",
            menu=pystray.Menu(
                pystray.MenuItem(self._status_text, None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(self._pause_text, self._toggle_pause),
                pystray.MenuItem("Синхронизировать сейчас", self._sync_now),
                pystray.MenuItem("Очистить музыку профиля", self._clear),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Настройки…", self._open_setup),
                pystray.MenuItem("Открыть журнал", self._open_log),
                pystray.MenuItem("Открыть папку данных", self._open_data),
                pystray.MenuItem("Перезапустить", self._restart),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Выход", self._exit),
            ),
        )

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
            self._notify(status.track.display_name, "Синхронизировано")
        elif status.kind == "error":
            self._notify(status.message, "Ошибка синхронизации")
        elif status.kind == "idle" and "очищена" in status.message:
            self._notify(status.message, "Очистка завершена")

    def _status_text(self, _item: pystray.MenuItem) -> str:
        return self.service.status.message[:80]

    def _pause_text(self, _item: pystray.MenuItem) -> str:
        return "Возобновить" if self.service.is_paused else "Приостановить"

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
                    "Окно настроек уже открыто.",
                    "Настройки",
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
            self._notify(str(exc), "Ошибка открытия настроек")
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
            "После сохранения приложение перезапустится автоматически.",
            "Настройки",
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
                    "Сначала сохраните или закройте окно настроек.",
                    "Перезапуск отложен",
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
            "Изменения не сохранены; работа продолжена с прежними настройками.",
            "Настройки закрыты",
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
            self._notify(str(exc), "Ошибка перезапуска")
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
