from __future__ import annotations

import asyncio
import inspect
import logging
import re
from collections.abc import Awaitable
from pathlib import Path
from typing import Any, TypeVar

from mutagen import MutagenError
from mutagen.mp3 import MP3
from telethon import TelegramClient, functions, types, utils
from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeFilename

from .localization import translate
from .models import Track

log = logging.getLogger(__name__)
_INVALID_FILENAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
T = TypeVar("T")


class TelegramError(RuntimeError):
    pass


class TelegramManager:
    def __init__(
        self,
        session_path: Path,
        api_id: int,
        api_hash: str,
        *,
        language: str = "ru",
    ) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._client = TelegramClient(str(session_path), api_id, api_hash, loop=self._loop)
        self._language = language
        self._closed = False
        self._playing_emoji_id = 0
        self._previous_emoji_status: Any | None = None
        self._playing_emoji_active = False

    def _run(self, operation: Awaitable[T]) -> T:
        if self._closed:
            raise TelegramError(translate("telegram.client_closed", self._language))
        return self._loop.run_until_complete(operation)

    def _disconnect(self) -> None:
        operation = self._client.disconnect()
        if inspect.isawaitable(operation):
            self._run(operation)

    def connect(self) -> None:
        self._run(self._client.connect())
        if not self._run(self._client.is_user_authorized()):
            self._disconnect()
            raise TelegramError(translate("telegram.unauthorized", self._language))
        log.info("Telegram подключён")

    def close(self) -> None:
        if self._closed:
            return
        try:
            if self._client.is_connected():
                try:
                    self.restore_emoji_status()
                except Exception:
                    log.exception(
                        "Не удалось восстановить Telegram emoji status при отключении"
                    )
                self._disconnect()
        finally:
            self._closed = True
            self._loop.close()
            asyncio.set_event_loop(None)

    def activate_playing_emoji(self, document_id: int) -> bool:
        if document_id <= 0:
            return False
        if self._playing_emoji_active:
            return True

        user = self._run(self._client.get_me())
        if user is None:
            raise TelegramError(translate("telegram.no_user", self._language))
        if not getattr(user, "premium", False):
            log.warning("Emoji status отключён: для него требуется Telegram Premium")
            return False

        previous_status = _emoji_status_for_update(
            getattr(user, "emoji_status", None),
            language=self._language,
        )
        request = functions.account.UpdateEmojiStatusRequest(
            types.EmojiStatus(document_id=document_id)
        )
        if self._run(self._client(request)) is False:
            raise TelegramError(
                translate("telegram.emoji_set_rejected", self._language)
            )

        self._previous_emoji_status = previous_status
        self._playing_emoji_id = document_id
        self._playing_emoji_active = True
        log.info("Telegram emoji status для активного nowplaying установлен")
        return True

    def restore_emoji_status(self) -> None:
        if not self._playing_emoji_active:
            return

        user = self._run(self._client.get_me())
        if user is None:
            raise TelegramError(translate("telegram.no_user", self._language))
        current_status = getattr(user, "emoji_status", None)
        if not _is_playing_emoji_status(current_status, self._playing_emoji_id):
            log.info(
                "Emoji status был изменён вручную; автоматическое восстановление пропущено"
            )
            self._forget_emoji_status()
            return

        previous_status = self._previous_emoji_status
        if previous_status is None:
            raise TelegramError(
                translate("telegram.emoji_previous_missing", self._language)
            )
        request = functions.account.UpdateEmojiStatusRequest(previous_status)
        if self._run(self._client(request)) is False:
            raise TelegramError(
                translate("telegram.emoji_restore_rejected", self._language)
            )
        self._forget_emoji_status()
        log.info("Исходный Telegram emoji status восстановлен")

    def _forget_emoji_status(self) -> None:
        self._playing_emoji_id = 0
        self._previous_emoji_status = None
        self._playing_emoji_active = False

    def send_track(self, path: Path, track: Track) -> Any:
        try:
            audio_info = MP3(path).info
            duration = max(0, round(audio_info.length)) if audio_info is not None else 0
        except (MutagenError, OSError, ValueError):
            duration = 0
        attributes = [
            DocumentAttributeAudio(
                duration=duration,
                title=track.title[:255],
                performer=track.artist[:255],
                voice=False,
            ),
            DocumentAttributeFilename(file_name=_track_filename(track)),
        ]
        message = self._run(
            self._client.send_file(
                "me",
                str(path),
                attributes=attributes,
                supports_streaming=True,
            )
        )
        document = getattr(getattr(message, "media", None), "document", None)
        if document is None:
            raise TelegramError(translate("telegram.no_document", self._language))
        return message, document

    def save_music(self, document: Any, *, unsave: bool, after: Any = None) -> None:
        request_class = getattr(functions.account, "SaveMusicRequest", None)
        if request_class is None:
            raise TelegramError(
                translate("telegram.telethon_too_old", self._language)
            )
        input_document = utils.get_input_document(document)
        input_after = utils.get_input_document(after) if after is not None else None
        result = self._run(
            self._client(request_class(input_document, unsave, input_after))
        )
        if result is False:
            key = (
                "telegram.music_remove_rejected"
                if unsave
                else "telegram.music_add_rejected"
            )
            raise TelegramError(translate(key, self._language))

    def delete_message(self, message_id: int) -> None:
        self._run(self._client.delete_messages("me", message_id))

    def get_documents(self, message_ids: list[int]) -> dict[int, Any]:
        if not message_ids:
            return {}
        messages = self._run(self._client.get_messages("me", ids=message_ids))
        if not isinstance(messages, list):
            messages = [messages]
        documents: dict[int, Any] = {}
        for message in messages:
            if message is None:
                continue
            document = getattr(getattr(message, "media", None), "document", None)
            if document is not None:
                documents[message.id] = document
        return documents


def _track_filename(track: Track) -> str:
    stem = _INVALID_FILENAME_RE.sub("_", f"{track.artist} - {track.title}").strip(" .")
    if not stem:
        stem = "track"
    return f"{stem[:180]}.mp3"


def _emoji_status_for_update(status: Any, *, language: str = "ru") -> Any:
    if status is None or isinstance(status, types.EmojiStatusEmpty):
        return types.EmojiStatusEmpty()
    if isinstance(status, types.EmojiStatusCollectible):
        return types.InputEmojiStatusCollectible(
            collectible_id=status.collectible_id,
            until=status.until,
        )
    if isinstance(status, types.EmojiStatus):
        return types.EmojiStatus(
            document_id=status.document_id,
            until=status.until,
        )
    raise TelegramError(
        translate(
            "telegram.emoji_unsupported",
            language,
            status_type=type(status).__name__,
        )
    )


def _is_playing_emoji_status(status: Any, document_id: int) -> bool:
    return (
        isinstance(status, types.EmojiStatus)
        and status.document_id == document_id
        and status.until is None
    )
