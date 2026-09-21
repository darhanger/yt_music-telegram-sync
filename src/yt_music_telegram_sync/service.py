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
from .localization import translate
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
        self._language = config.ui_language
        self._status_callback = status_callback
        self._session_path = session_path or default_session_path()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._paused = threading.Event()
        self._commands: SimpleQueue[str] = SimpleQueue()
        self._thread: threading.Thread | None = None
        self._status = ServiceStatus(
            "stopped",
            translate("service.stopped", self._language),
        )
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
            self._set_status(
                "running",
                translate("service.resumed", self._language),
            )
        else:
            self._paused.set()
            self._commands.put("pause")
            self._set_status(
                "paused",
                translate("service.paused", self._language),
            )
        self._wake_event.set()
        return self._paused.is_set()

    def sync_now(self) -> None:
        self._wake_event.set()

    def clear_profile_music(self) -> None:
        self._commands.put("clear")
        self._wake_event.set()

    def _run(self) -> None:
        self._set_status(
            "starting",
            translate("service.connecting", self._language),
        )
        artwork = ArtworkLoader()
        telegram = TelegramManager(
            self._session_path,
            self.config.telegram_api_id,
            self.config.telegram_api_hash,
            language=self._language,
        )
        lastfm = LastFmClient(
            self.config.lastfm_api_key,
            self.config.lastfm_username,
            language=self._language,
        )
        sync: TrackSyncService | None = None
        try:
            telegram.connect()
            user = lastfm.get_user()
            self._set_status(
                "running",
                translate(
                    "service.connected",
                    self._language,
                    username=user.username,
                ),
            )
            state = StateStore()
            channel_enabled = self.config.telegram_output_mode in {
                "personal_channel",
                "profile_and_channel",
            }
            profile_music_enabled = (
                self.config.telegram_output_mode != "personal_channel"
            )
            personal_channel_id = (
                self.config.telegram_personal_channel_id
                if channel_enabled
                else 0
            )
            if channel_enabled and profile_music_enabled:
                destination = f"profile_and_channel:{personal_channel_id}"
            elif channel_enabled:
                destination = f"personal_channel:{personal_channel_id}"
            else:
                destination = "profile_music"
            initial_entries = self._restore_entries(
                state,
                telegram,
                destination=destination,
                personal_channel_id=personal_channel_id,
                profile_music_enabled=profile_music_enabled,
            )
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
                    (
                        StoredTrack(
                            entry.track,
                            entry.message_id,
                            entry.channel_message_id,
                        )
                        for entry in entries
                    ),
                    destination=destination,
                ),
                playing_emoji_id=(
                    self.config.telegram_playing_emoji_id
                    if self.config.telegram_playing_emoji_enabled
                    else 0
                ),
                personal_channel_id=personal_channel_id,
                profile_music_enabled=profile_music_enabled,
                language=self._language,
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
                self._set_status(
                    "stopped",
                    translate("service.stopped", self._language),
                )

    def _restore_entries(
        self,
        state: StateStore,
        telegram: TelegramManager,
        *,
        destination: str = "profile_music",
        personal_channel_id: int = 0,
        profile_music_enabled: bool = True,
    ) -> list[CachedTrack]:
        stored = state.load(destination=destination)
        channel_documents: dict[int, object] = {}
        if profile_music_enabled:
            documents = telegram.get_documents(
                [entry.message_id for entry in stored]
            )
            channel_message_ids = [
                entry.channel_message_id
                for entry in stored
                if entry.channel_message_id is not None
            ]
            channel_documents = (
                telegram.get_documents(
                    channel_message_ids,
                    personal_channel_id=personal_channel_id,
                )
                if personal_channel_id and channel_message_ids
                else {}
            )
        else:
            documents = telegram.get_documents(
                [entry.message_id for entry in stored],
                personal_channel_id=personal_channel_id,
            )
        restored = [
            CachedTrack(
                entry.track,
                entry.message_id,
                documents[entry.message_id],
                channel_message_id=(
                    entry.channel_message_id
                    if entry.channel_message_id in channel_documents
                    else None
                ),
            )
            for entry in stored
            if entry.message_id in documents
        ][-self.config.cache_size :]
        state.save(
            (
                StoredTrack(
                    entry.track,
                    entry.message_id,
                    entry.channel_message_id,
                )
                for entry in restored
            ),
            destination=destination,
        )
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
                            key = (
                                "service.idle_cleaned"
                                if (
                                    self.config.remove_when_idle
                                    or self.config.telegram_output_mode
                                    in {"personal_channel", "profile_and_channel"}
                                )
                                else "service.idle"
                            )
                            message = translate(key, self._language)
                            self._set_status("idle", message)
                        last_identity = None
                else:
                    absent_count = 0
                    sync.handle_scrobbling_active()
                    if track.identity != last_identity or sync.active_track is None:
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
                    self._set_status(
                        "idle",
                        translate("service.profile_cleared", self._language),
                    )
                except Exception as exc:
                    log.exception("Не удалось очистить музыку профиля")
                    self._set_status(
                        "error",
                        translate("service.clear_error", self._language, error=exc),
                    )
            elif command == "pause":
                sync.handle_pause()

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
