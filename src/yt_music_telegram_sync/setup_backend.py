"""Network operations used by the Qt setup wizard."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from telethon import TelegramClient, functions, types, utils
from telethon.errors import SessionPasswordNeededError

from .config import ConfigurationError
from .localization import translate
from .telegram import TelegramError, _emoji_status_for_update


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


async def _telegram_capture_personal_channel(
    session_path: Path,
    api_id: int,
    api_hash: str,
    selection_prompt: Callable[[], bool],
    *,
    language: str = "ru",
) -> tuple[int, str] | None:
    client = TelegramClient(str(session_path), api_id, api_hash)
    original_channel = None
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise ConfigurationError(
                translate("channel.telegram_unauthorized", language)
            )
        original_result = await client(functions.users.GetFullUserRequest("me"))
        original_full_user = getattr(original_result, "full_user", None)
        if original_full_user is None:
            raise ConfigurationError(translate("channel.no_user", language))
        original_id = int(
            getattr(original_full_user, "personal_channel_id", 0) or 0
        )
        original_channel = types.InputChannelEmpty()
        if original_id:
            original_channels = await _telegram_personal_channels(client)
            original_entity = original_channels.get(original_id)
            if original_entity is None:
                raise ConfigurationError(
                    translate("channel.original_unavailable", language)
                )
            original_channel = utils.get_input_channel(original_entity)

        if not selection_prompt():
            return None

        selected_result = await client(functions.users.GetFullUserRequest("me"))
        selected_full_user = getattr(selected_result, "full_user", None)
        if selected_full_user is None:
            raise ConfigurationError(translate("channel.no_user", language))
        selected_id = int(
            getattr(selected_full_user, "personal_channel_id", 0) or 0
        )
        if not selected_id:
            raise ConfigurationError(translate("channel.not_selected", language))
        selected_channels = await _telegram_personal_channels(client)
        selected_channel = selected_channels.get(selected_id)
        if selected_channel is None:
            raise ConfigurationError(translate("channel.unavailable", language))
        return selected_id, str(getattr(selected_channel, "title", selected_id))
    finally:
        try:
            if original_channel is not None:
                restored = await client(
                    functions.account.UpdatePersonalChannelRequest(original_channel)
                )
                if restored is False:
                    raise TelegramError(
                        translate("channel.restore_rejected", language)
                    )
        finally:
            await client.disconnect()


async def _telegram_personal_channels(client: TelegramClient) -> dict[int, Any]:
    result = await client(
        functions.channels.GetAdminedPublicChannelsRequest(for_personal=True)
    )
    return {
        int(channel.id): channel
        for channel in getattr(result, "chats", [])
        if isinstance(channel, types.Channel)
    }
