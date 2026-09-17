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
from telethon import TelegramClient, functions, utils
from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeFilename

from .models import Track

log = logging.getLogger(__name__)
_INVALID_FILENAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
T = TypeVar("T")


class TelegramError(RuntimeError):
    pass


class TelegramManager:
    def __init__(self, session_path: Path, api_id: int, api_hash: str) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._client = TelegramClient(str(session_path), api_id, api_hash, loop=self._loop)
        self._closed = False

    def _run(self, operation: Awaitable[T]) -> T:
        if self._closed:
            raise TelegramError("Telegram-клиент уже закрыт")
        return self._loop.run_until_complete(operation)

    def _disconnect(self) -> None:
        operation = self._client.disconnect()
        if inspect.isawaitable(operation):
            self._run(operation)

    def connect(self) -> None:
        self._run(self._client.connect())
        if not self._run(self._client.is_user_authorized()):
            self._disconnect()
            raise TelegramError("Telegram не авторизован. Запустите мастер настройки.")
        log.info("Telegram подключён")

    def close(self) -> None:
        if self._closed:
            return
        try:
            if self._client.is_connected():
                self._disconnect()
        finally:
            self._closed = True
            self._loop.close()
            asyncio.set_event_loop(None)

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
            raise TelegramError("Telegram не вернул документ после загрузки трека")
        return message, document

    def save_music(self, document: Any, *, unsave: bool, after: Any = None) -> None:
        request_class = getattr(functions.account, "SaveMusicRequest", None)
        if request_class is None:
            raise TelegramError(
                "Установленная версия Telethon не поддерживает Telegram Music on Profile"
            )
        input_document = utils.get_input_document(document)
        input_after = utils.get_input_document(after) if after is not None else None
        result = self._run(
            self._client(request_class(input_document, unsave, input_after))
        )
        if result is False:
            action = "удаление" if unsave else "добавление"
            raise TelegramError(f"Telegram отклонил {action} музыки профиля")

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
