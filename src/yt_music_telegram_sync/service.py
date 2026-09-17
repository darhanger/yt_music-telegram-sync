from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, SimpleQueue
from typing import Literal

from .audio import ArtworkLoader, PlaceholderBackend, YtDlpBackend
from .config import AppConfig, default_session_path
from .lastfm import LastFmClient, LastFmError
from .models import Track
from .state import StateStore, StoredTrack
from .sync import CachedTrack, TrackSyncService
from .telegram import TelegramManager

log = logging.getLogger(__name__)

StatusKind = Literal["starting", "running", "paused", "idle", "error", "stopped"]


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    kind: StatusKind
    message: str
    track: Track | None = None


StatusCallback = Callable[[ServiceStatus], None]


class SyncApplicationService:
    def __init__(
        self,
        config: AppConfig,
        *,
        status_callback: StatusCallback | None = None,
        session_path: Path | None = None,
    ) -> None:
        self.config = config
        self._status_callback = status_callback
        self._session_path = session_path or default_session_path()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._paused = threading.Event()
        self._commands: SimpleQueue[str] = SimpleQueue()
        self._thread: threading.Thread | None = None
        self._status = ServiceStatus("stopped", "Остановлено")
        self._status_lock = threading.Lock()

    @property
    def status(self) -> ServiceStatus:
        with self._status_lock:
            return self._status

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def set_status_callback(self, callback: StatusCallback | None) -> None:
        self._status_callback = callback

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="sync-service", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 15.0) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def toggle_pause(self) -> bool:
        if self._paused.is_set():
            self._paused.clear()
            self._set_status("running", "Синхронизация возобновлена")
        else:
            self._paused.set()
            self._set_status("paused", "Синхронизация приостановлена")
        self._wake_event.set()
        return self._paused.is_set()

    def sync_now(self) -> None:
        self._wake_event.set()

    def clear_profile_music(self) -> None:
        self._commands.put("clear")
        self._wake_event.set()

    def _run(self) -> None:
        self._set_status("starting", "Подключение к Last.fm и Telegram…")
        artwork = ArtworkLoader()
        telegram = TelegramManager(
            self._session_path,
            self.config.telegram_api_id,
            self.config.telegram_api_hash,
        )
        lastfm = LastFmClient(self.config.lastfm_api_key, self.config.lastfm_username)
        sync: TrackSyncService | None = None
        try:
            telegram.connect()
            user = lastfm.get_user()
            self._set_status(
                "running", f"Last.fm подключён: {user.username}; проверка nowplaying…"
            )
            state = StateStore()
            initial_entries = self._restore_entries(state, telegram)
            placeholder = PlaceholderBackend(artwork)
            downloader = YtDlpBackend(artwork)
            immediate = downloader if self.config.audio_mode == "audio" else placeholder
            replacement = downloader if self.config.audio_mode == "mixed" else None
            sync = TrackSyncService(
                telegram,
                immediate,
                placeholder,
                cache_size=self.config.cache_size,
                replacement_backend=replacement,
                download_workers=self.config.download_workers,
                initial_entries=initial_entries,
                cache_changed=lambda entries: state.save(
                    StoredTrack(entry.track, entry.message_id) for entry in entries
                ),
            )
            self._poll_loop(lastfm, sync)
        except Exception as exc:
            log.exception("Сервис остановлен из-за ошибки")
            self._set_status("error", str(exc))
        finally:
            if sync is not None:
                sync.close()
            lastfm.close()
            telegram.close()
            artwork.close()
            if self.status.kind != "error":
                self._set_status("stopped", "Остановлено")

    def _restore_entries(
        self, state: StateStore, telegram: TelegramManager
    ) -> list[CachedTrack]:
        stored = state.load()
        documents = telegram.get_documents([entry.message_id for entry in stored])
        restored = [
            CachedTrack(entry.track, entry.message_id, documents[entry.message_id])
            for entry in stored
            if entry.message_id in documents
        ][-self.config.cache_size :]
        state.save(StoredTrack(entry.track, entry.message_id) for entry in restored)
        if restored:
            log.info("Восстановлено треков из предыдущего запуска: %d", len(restored))
        return restored

    def _poll_loop(self, lastfm: LastFmClient, sync: TrackSyncService) -> None:
        absent_count = 0
        failures = 0
        last_identity: tuple[str, ...] | None = None

        while not self._stop_event.is_set():
            self._process_commands(sync)
            sync.process_ready_replacements()

            if self._paused.is_set():
                self._wait(0.5)
                continue

            started = time.monotonic()
            try:
                track = lastfm.get_now_playing()
                if track is None:
                    absent_count += 1
                    if absent_count >= self.config.absent_confirmations:
                        sync.handle_no_track(self.config.remove_when_idle)
                        if self.status.kind != "idle":
                            message = "Last.fm: сейчас ничего не играет"
                            if self.config.remove_when_idle:
                                message += "; музыка профиля очищена"
                            self._set_status("idle", message)
                        last_identity = None
                else:
                    absent_count = 0
                    if track.identity != last_identity:
                        sync.handle_track(track)
                        last_identity = track.identity
                    if self.status.kind != "running" or self.status.track != track:
                        self._set_status("running", track.display_name, track)
                failures = 0
            except LastFmError as exc:
                failures += 1
                delay = min(
                    300.0, self.config.poll_interval_seconds * (2 ** min(failures, 6))
                )
                log.warning("Last.fm: %s; повтор через %.0f с", exc, delay)
                self._set_status("error", f"Last.fm: {exc}")
                self._wait(delay)
                continue
            except Exception as exc:
                failures += 1
                delay = min(
                    300.0, self.config.poll_interval_seconds * (2 ** min(failures, 6))
                )
                log.exception("Ошибка синхронизации; повтор через %.0f с", delay)
                self._set_status("error", str(exc))
                self._wait(delay)
                continue

            elapsed = time.monotonic() - started
            self._wait(max(0.1, self.config.poll_interval_seconds - elapsed))

    def _process_commands(self, sync: TrackSyncService) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except Empty:
                return
            if command == "clear":
                try:
                    sync.clear()
                    self._set_status("idle", "Музыка профиля очищена")
                except Exception as exc:
                    log.exception("Не удалось очистить музыку профиля")
                    self._set_status("error", f"Очистка: {exc}")

    def _wait(self, timeout: float) -> None:
        self._wake_event.wait(timeout)
        self._wake_event.clear()

    def _set_status(
        self, kind: StatusKind, message: str, track: Track | None = None
    ) -> None:
        status = ServiceStatus(kind, message, track)
        with self._status_lock:
            previous = self._status
            self._status = status
        if status != previous:
            log.info("Статус: %s", message)
            if self._status_callback is not None:
                try:
                    self._status_callback(status)
                except Exception:
                    log.exception("Ошибка обработчика статуса")
