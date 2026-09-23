from __future__ import annotations

import asyncio
import inspect
import logging
import re
import threading
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from mutagen import MutagenError
from mutagen.mp3 import MP3
from telethon import TelegramClient, functions, types, utils
from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeFilename

from .localization import translate
from .models import Track
from .state import StoredEmojiStatus, TelegramRestoreState

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
        restore_state: TelegramRestoreState | None = None,
        restore_state_changed: Callable[[TelegramRestoreState], None] | None = None,
    ) -> None:
        pending = restore_state or TelegramRestoreState()
        self._loop = asyncio.new_event_loop()
        self._client = TelegramClient(str(session_path), api_id, api_hash, loop=self._loop)
        self._loop_thread = threading.Thread(
            target=self._run_event_loop,
            name="telegram-event-loop",
            daemon=True,
        )
        self._loop_thread.start()
        self._language = language
        self._closed = False
        self._restore_state_changed = restore_state_changed
        self._playing_emoji_id = pending.playing_emoji_id
        self._previous_emoji_status: Any | None = _emoji_status_from_stored(
            pending.previous_emoji_status
        )
        self._playing_emoji_active = (
            self._playing_emoji_id > 0 and self._previous_emoji_status is not None
        )
        self._playing_personal_channel_id = pending.playing_personal_channel_id
        self._previous_personal_channel_id = pending.previous_personal_channel_id
        self._previous_personal_channel: Any | None = None
        self._playing_personal_channel_active = (
            self._playing_personal_channel_id > 0
        )
        self._personal_channels: dict[int, Any] = {}

    @property
    def playing_emoji_active(self) -> bool:
        return self._playing_emoji_active

    @property
    def playing_personal_channel_active(self) -> bool:
        return self._playing_personal_channel_active

    def _run(self, operation: Awaitable[T]) -> T:
        if self._closed:
            raise TelegramError(translate("telegram.client_closed", self._language))
        future = asyncio.run_coroutine_threadsafe(
            _await_operation(operation),
            self._loop,
        )
        return future.result()

    def _run_event_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()

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

    def restore_pending_presence(self) -> None:
        if self._playing_personal_channel_active:
            try:
                self.restore_personal_channel()
            except Exception:
                log.exception(
                    "Не удалось восстановить личный канал после предыдущего запуска"
                )
        if self._playing_emoji_active:
            try:
                self.restore_emoji_status()
            except Exception:
                log.exception(
                    "Не удалось восстановить Telegram emoji status после предыдущего запуска"
                )

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
                try:
                    self.restore_personal_channel()
                except Exception:
                    log.exception(
                        "Не удалось восстановить личный канал Telegram при отключении"
                    )
                self._disconnect()
        finally:
            self._closed = True
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop_thread.join(timeout=5.0)
            if self._loop_thread.is_alive():
                log.warning("Поток Telegram event loop не завершился вовремя")

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
        self._previous_emoji_status = previous_status
        self._playing_emoji_id = document_id
        self._playing_emoji_active = True
        try:
            self._notify_restore_state_changed()
        except Exception:
            self._forget_emoji_status(notify=False)
            raise

        request = functions.account.UpdateEmojiStatusRequest(
            types.EmojiStatus(document_id=document_id)
        )
        # A connection failure leaves the recovery record intact because the server
        # may already have applied the request.
        result = self._run(self._client(request))
        if result is False:
            self._forget_emoji_status()
            raise TelegramError(
                translate("telegram.emoji_set_rejected", self._language)
            )
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

    def _forget_emoji_status(self, *, notify: bool = True) -> None:
        self._playing_emoji_id = 0
        self._previous_emoji_status = None
        self._playing_emoji_active = False
        if notify:
            self._notify_restore_state_changed()

    def activate_personal_channel(self, channel_id: int) -> bool:
        if channel_id <= 0:
            return False
        if self._playing_personal_channel_active:
            return True

        previous_id = self._current_personal_channel_id()
        channel = self._get_personal_channel(channel_id)
        previous_channel = (
            utils.get_input_channel(self._get_personal_channel(previous_id))
            if previous_id
            else types.InputChannelEmpty()
        )
        request_class = getattr(functions.account, "UpdatePersonalChannelRequest", None)
        if request_class is None:
            raise TelegramError(
                translate("telegram.telethon_channel_too_old", self._language)
            )
        self._previous_personal_channel_id = previous_id
        self._previous_personal_channel = previous_channel
        self._playing_personal_channel_id = channel_id
        self._playing_personal_channel_active = True
        try:
            self._notify_restore_state_changed()
        except Exception:
            self._forget_personal_channel(notify=False)
            raise

        if previous_id != channel_id:
            # Preserve the record on a connection failure because the remote result
            # is ambiguous.
            result = self._run(
                self._client(request_class(utils.get_input_channel(channel)))
            )
            if result is False:
                self._forget_personal_channel()
                raise TelegramError(
                    translate("telegram.channel_set_rejected", self._language)
                )
        log.info("Личный канал Telegram для активного nowplaying установлен")
        return True

    def restore_personal_channel(self) -> None:
        if not self._playing_personal_channel_active:
            return

        current_id = self._current_personal_channel_id()
        if current_id != self._playing_personal_channel_id:
            log.info(
                "Личный канал был изменён вручную; автоматическое восстановление пропущено"
            )
            self._forget_personal_channel()
            return

        previous_channel = self._previous_personal_channel
        if previous_channel is None:
            previous_channel = (
                utils.get_input_channel(
                    self._get_personal_channel(self._previous_personal_channel_id)
                )
                if self._previous_personal_channel_id
                else types.InputChannelEmpty()
            )
        request_class = getattr(functions.account, "UpdatePersonalChannelRequest", None)
        if request_class is None:
            raise TelegramError(
                translate("telegram.telethon_channel_too_old", self._language)
            )
        if self._previous_personal_channel_id != self._playing_personal_channel_id:
            result = self._run(self._client(request_class(previous_channel)))
            if result is False:
                raise TelegramError(
                    translate("telegram.channel_restore_rejected", self._language)
                )
        self._forget_personal_channel()
        log.info("Исходный личный канал Telegram восстановлен")

    def _forget_personal_channel(self, *, notify: bool = True) -> None:
        self._playing_personal_channel_id = 0
        self._previous_personal_channel_id = 0
        self._previous_personal_channel = None
        self._playing_personal_channel_active = False
        if notify:
            self._notify_restore_state_changed()

    def _notify_restore_state_changed(self) -> None:
        if self._restore_state_changed is None:
            return
        previous_status = (
            _stored_emoji_status(self._previous_emoji_status)
            if self._playing_emoji_active
            else None
        )
        self._restore_state_changed(
            TelegramRestoreState(
                playing_emoji_id=(
                    self._playing_emoji_id if previous_status is not None else 0
                ),
                previous_emoji_status=previous_status,
                playing_personal_channel_id=(
                    self._playing_personal_channel_id
                    if self._playing_personal_channel_active
                    else 0
                ),
                previous_personal_channel_id=(
                    self._previous_personal_channel_id
                    if self._playing_personal_channel_active
                    else 0
                ),
            )
        )

    def _current_personal_channel_id(self) -> int:
        result = self._run(
            self._client(functions.users.GetFullUserRequest("me"))
        )
        full_user = getattr(result, "full_user", None)
        if full_user is None:
            raise TelegramError(translate("telegram.no_user", self._language))
        return int(getattr(full_user, "personal_channel_id", 0) or 0)

    def _get_personal_channel(self, channel_id: int) -> Any:
        cached = self._personal_channels.get(channel_id)
        if cached is not None:
            return cached
        request_class = getattr(
            functions.channels, "GetAdminedPublicChannelsRequest", None
        )
        if request_class is None:
            raise TelegramError(
                translate("telegram.telethon_channel_too_old", self._language)
            )
        result = self._run(
            self._client(request_class(for_personal=True))
        )
        self._personal_channels.update(
            {
                int(channel.id): channel
                for channel in getattr(result, "chats", [])
                if isinstance(channel, types.Channel)
            }
        )
        try:
            return self._personal_channels[channel_id]
        except KeyError as exc:
            raise TelegramError(
                translate("telegram.channel_unavailable", self._language)
            ) from exc

    def send_track(
        self, path: Path, track: Track, *, personal_channel_id: int = 0
    ) -> Any:
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
                self._message_peer(personal_channel_id),
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

    def send_document(self, document: Any, *, personal_channel_id: int) -> Any:
        message = self._run(
            self._client.send_file(
                self._message_peer(personal_channel_id),
                document,
                supports_streaming=True,
            )
        )
        sent_document = getattr(getattr(message, "media", None), "document", None)
        if sent_document is None:
            raise TelegramError(translate("telegram.no_document", self._language))
        return message, sent_document

    def delete_message(self, message_id: int, *, personal_channel_id: int = 0) -> None:
        self._run(
            self._client.delete_messages(
                self._message_peer(personal_channel_id), message_id
            )
        )

    def get_documents(
        self, message_ids: list[int], *, personal_channel_id: int = 0
    ) -> dict[int, Any]:
        if not message_ids:
            return {}
        messages = self._run(
            self._client.get_messages(
                self._message_peer(personal_channel_id), ids=message_ids
            )
        )
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

    def _message_peer(self, personal_channel_id: int) -> Any:
        if personal_channel_id <= 0:
            return "me"
        return self._get_personal_channel(personal_channel_id)


def _track_filename(track: Track) -> str:
    stem = _INVALID_FILENAME_RE.sub("_", f"{track.artist} - {track.title}").strip(" .")
    if not stem:
        stem = "track"
    return f"{stem[:180]}.mp3"


async def _await_operation(operation: Awaitable[T]) -> T:
    return await operation


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


def _stored_emoji_status(status: Any) -> StoredEmojiStatus | None:
    if status is None:
        return None
    if isinstance(status, types.EmojiStatusEmpty):
        return StoredEmojiStatus(kind="empty")
    if isinstance(
        status,
        (types.EmojiStatusCollectible, types.InputEmojiStatusCollectible),
    ):
        return StoredEmojiStatus(
            kind="collectible",
            status_id=int(status.collectible_id),
            until=_emoji_until_timestamp(getattr(status, "until", None)),
        )
    if isinstance(status, types.EmojiStatus):
        return StoredEmojiStatus(
            kind="emoji",
            status_id=int(status.document_id),
            until=_emoji_until_timestamp(getattr(status, "until", None)),
        )
    return None


def _emoji_status_from_stored(status: StoredEmojiStatus | None) -> Any | None:
    if status is None:
        return None
    until = (
        datetime.fromtimestamp(status.until, tz=UTC)
        if status.until is not None
        else None
    )
    if status.kind == "empty":
        return types.EmojiStatusEmpty()
    if status.kind == "collectible":
        return types.InputEmojiStatusCollectible(
            collectible_id=status.status_id,
            until=until,
        )
    return types.EmojiStatus(document_id=status.status_id, until=until)


def _emoji_until_timestamp(value: object) -> int | None:
    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, int):
        return value
    return None


def _is_playing_emoji_status(status: Any, document_id: int) -> bool:
    return (
        isinstance(status, types.EmojiStatus)
        and status.document_id == document_id
        and status.until is None
    )
