from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audio import PlaceholderBackend, TrackBackend
from .localization import translate
from .models import Track
from .telegram import TelegramError, TelegramManager

log = logging.getLogger(__name__)


@dataclass(slots=True)
class CachedTrack:
    track: Track
    message_id: int
    document: Any
    replacement_sequence: int | None = None
    replacement_state: str = "none"
    replacement_path: Path | None = None


class TrackSyncService:
    def __init__(
        self,
        telegram: TelegramManager,
        immediate_backend: TrackBackend,
        fallback_backend: PlaceholderBackend,
        *,
        cache_size: int,
        replacement_backend: TrackBackend | None = None,
        download_workers: int = 2,
        initial_entries: list[CachedTrack] | None = None,
        cache_changed: Callable[[list[CachedTrack]], None] | None = None,
        playing_emoji_id: int = 0,
        language: str = "ru",
    ) -> None:
        self._telegram = telegram
        self._immediate_backend = immediate_backend
        self._fallback_backend = fallback_backend
        self._replacement_backend = replacement_backend
        self._cache_size = cache_size
        self._cache: OrderedDict[tuple[str, ...], CachedTrack] = OrderedDict()
        self._active_identity: tuple[str, ...] | None = None
        self._replacement_queue: dict[int, CachedTrack] = {}
        self._replacement_sequence = 0
        self._lock = threading.RLock()
        self._cache_changed = cache_changed
        self._playing_emoji_id = playing_emoji_id
        self._language = language
        self._playing_emoji_active = False
        self._next_emoji_attempt = 0.0
        if initial_entries:
            for entry in initial_entries[-cache_size:]:
                self._cache[entry.track.identity] = entry
        self._executor = ThreadPoolExecutor(
            max_workers=download_workers, thread_name_prefix="audio-download"
        )

    @property
    def active_track(self) -> Track | None:
        if self._active_identity is None:
            return None
        entry = self._cache.get(self._active_identity)
        return entry.track if entry else None

    def handle_track(self, track: Track) -> None:
        identity = track.identity
        entry = self._cache.get(identity)
        if entry is not None:
            self._cache.move_to_end(identity)
            self._active_identity = identity
            self._telegram.save_music(entry.document, unsave=True)
            self._telegram.save_music(entry.document, unsave=False)
            self._notify_cache_changed()
            log.info("Трек возвращён в начало профиля: %s", track.display_name)
            return

        entry = self._create_entry(track)
        if len(self._cache) >= self._cache_size:
            try:
                self._evict_oldest()
            except Exception:
                try:
                    self._remove_entry(entry)
                except Exception:
                    log.exception(
                        "Не удалось откатить добавление трека: %s",
                        track.display_name,
                    )
                raise
        self._cache[identity] = entry
        self._active_identity = identity
        self._schedule_replacement(entry)
        self._notify_cache_changed()
        log.info("Трек добавлен в Telegram: %s", track.display_name)

    def handle_no_track(self, remove_when_idle: bool) -> None:
        self.handle_scrobbling_inactive()
        self._active_identity = None
        if remove_when_idle:
            self.clear()

    def handle_scrobbling_active(self) -> None:
        now = time.monotonic()
        if (
            self._playing_emoji_id <= 0
            or self._playing_emoji_active
            or now < self._next_emoji_attempt
        ):
            return
        try:
            activated = self._telegram.activate_playing_emoji(self._playing_emoji_id)
        except Exception:
            self._next_emoji_attempt = now + 60.0
            log.exception("Не удалось установить Telegram emoji status")
            return
        if activated:
            self._playing_emoji_active = True
            self._next_emoji_attempt = 0.0
        else:
            self._next_emoji_attempt = now + 300.0

    def handle_scrobbling_inactive(self) -> None:
        if self._playing_emoji_id <= 0 or not self._playing_emoji_active:
            self._next_emoji_attempt = 0.0
            return
        now = time.monotonic()
        if now < self._next_emoji_attempt:
            return
        try:
            self._telegram.restore_emoji_status()
        except Exception:
            self._next_emoji_attempt = now + 60.0
            log.exception("Не удалось восстановить Telegram emoji status")
            return
        self._playing_emoji_active = False
        self._next_emoji_attempt = 0.0

    def clear(self) -> None:
        failed: list[CachedTrack] = []
        for identity, entry in list(self._cache.items()):
            try:
                self._remove_entry(entry)
            except Exception:
                failed.append(entry)
                log.exception(
                    "Не удалось удалить трек из музыки профиля: %s",
                    entry.track.display_name,
                )
            else:
                self._cache.pop(identity, None)
                if self._active_identity == identity:
                    self._active_identity = None
        self._notify_cache_changed()
        if failed:
            raise TelegramError(
                translate(
                    "sync.cleanup_failed",
                    self._language,
                    count=len(failed),
                )
            )
        log.info("Музыкальный кэш Telegram очищен")

    def process_ready_replacements(self, limit: int = 1) -> None:
        processed = 0
        while processed < limit:
            with self._lock:
                if not self._replacement_queue:
                    return
                sequence = min(self._replacement_queue)
                entry = self._replacement_queue[sequence]
                state = entry.replacement_state
                if state == "pending":
                    return
                self._replacement_queue.pop(sequence, None)

            if state == "ready":
                try:
                    self._apply_replacement(entry)
                except Exception:
                    log.exception(
                        "Не удалось заменить placeholder для %s",
                        entry.track.display_name,
                    )
            self._cleanup_replacement(entry)
            entry.replacement_state = "applied"
            processed += 1

    def close(self) -> None:
        if self._playing_emoji_active:
            try:
                self._telegram.restore_emoji_status()
            except Exception:
                log.exception(
                    "Не удалось восстановить Telegram emoji status при завершении"
                )
            else:
                self._playing_emoji_active = False
        with self._lock:
            for entry in self._replacement_queue.values():
                if entry.replacement_state == "pending":
                    entry.replacement_state = "skipped"
        self._executor.shutdown(wait=True, cancel_futures=True)
        for entry in list(self._replacement_queue.values()):
            self._cleanup_replacement(entry)
        self._replacement_queue.clear()

    def _create_entry(self, track: Track) -> CachedTrack:
        path = _temporary_mp3_path()
        message = None
        try:
            if not self._immediate_backend.create(path, track):
                self._fallback_backend.create(path, track)
            message, document = self._telegram.send_track(path, track)
            self._telegram.save_music(document, unsave=False)
            return CachedTrack(track=track, message_id=message.id, document=document)
        except Exception:
            if message is not None:
                try:
                    self._telegram.delete_message(message.id)
                except Exception:
                    log.exception("Не удалось удалить незавершённую загрузку Telegram")
            raise
        finally:
            path.unlink(missing_ok=True)

    def _schedule_replacement(self, entry: CachedTrack) -> None:
        if self._replacement_backend is None:
            return
        with self._lock:
            sequence = self._replacement_sequence
            self._replacement_sequence += 1
            entry.replacement_sequence = sequence
            entry.replacement_state = "pending"
            self._replacement_queue[sequence] = entry
        self._executor.submit(self._prepare_replacement, entry)

    def _prepare_replacement(self, entry: CachedTrack) -> None:
        path = _temporary_mp3_path()
        try:
            assert self._replacement_backend is not None
            result = self._replacement_backend.create(path, entry.track)
            with self._lock:
                if entry.replacement_state == "skipped":
                    path.unlink(missing_ok=True)
                elif result:
                    entry.replacement_path = path
                    entry.replacement_state = "ready"
                else:
                    entry.replacement_state = "failed"
                    path.unlink(missing_ok=True)
        except Exception:
            log.exception("Ошибка фоновой загрузки %s", entry.track.display_name)
            with self._lock:
                entry.replacement_state = "failed"
            path.unlink(missing_ok=True)

    def _apply_replacement(self, entry: CachedTrack) -> None:
        current = self._cache.get(entry.track.identity)
        if current is not entry or entry.replacement_path is None:
            return
        after = self._document_after(entry.track.identity)
        message, document = self._telegram.send_track(
            entry.replacement_path, entry.track
        )
        try:
            self._telegram.save_music(document, unsave=False, after=after)
        except Exception:
            try:
                self._telegram.delete_message(message.id)
            except Exception:
                log.exception("Не удалось удалить незавершённую замену Telegram")
            raise
        try:
            self._telegram.save_music(entry.document, unsave=True)
        except Exception:
            try:
                self._telegram.save_music(document, unsave=True)
                self._telegram.delete_message(message.id)
            except Exception:
                log.exception("Не удалось откатить замену Telegram")
            raise
        old_message_id = entry.message_id
        entry.message_id = message.id
        entry.document = document
        try:
            self._telegram.delete_message(old_message_id)
        except Exception:
            log.exception("Не удалось удалить старый placeholder из Saved Messages")
        self._notify_cache_changed()
        log.info("Placeholder заменён аудиофайлом: %s", entry.track.display_name)

    def _document_after(self, identity: tuple[str, ...]) -> Any:
        keys = list(self._cache)
        try:
            index = keys.index(identity)
        except ValueError:
            return None
        if index + 1 >= len(keys):
            return None
        return self._cache[keys[index + 1]].document

    def _evict_oldest(self) -> None:
        identity, entry = next(iter(self._cache.items()))
        self._remove_entry(entry)
        self._cache.pop(identity, None)
        self._notify_cache_changed()

    def _remove_entry(self, entry: CachedTrack) -> None:
        with self._lock:
            if entry.replacement_state == "pending":
                entry.replacement_state = "skipped"
        self._telegram.save_music(entry.document, unsave=True)
        self._telegram.delete_message(entry.message_id)

    @staticmethod
    def _cleanup_replacement(entry: CachedTrack) -> None:
        if entry.replacement_path is not None:
            entry.replacement_path.unlink(missing_ok=True)
            entry.replacement_path = None

    def _notify_cache_changed(self) -> None:
        if self._cache_changed is None:
            return
        try:
            self._cache_changed(list(self._cache.values()))
        except Exception:
            log.exception("Не удалось сохранить состояние кэша")


def _temporary_mp3_path() -> Path:
    descriptor, name = tempfile.mkstemp(prefix="ytmts-", suffix=".mp3")
    os.close(descriptor)
    return Path(name)
