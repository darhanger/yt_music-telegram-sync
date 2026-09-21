import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from telethon import functions, types

from yt_music_telegram_sync.models import Track
from yt_music_telegram_sync.telegram import (
    TelegramManager,
    _emoji_status_for_update,
    _track_filename,
)


class TelegramFilenameTests(unittest.TestCase):
    def test_sanitizes_and_limits_filename(self) -> None:
        track = Track(title='Bad:/Name?"' + "x" * 300, artist="A|B")
        filename = _track_filename(track)
        self.assertLessEqual(len(filename), 184)
        for invalid in '\\/:*?"<>|':
            self.assertNotIn(invalid, filename)
        self.assertTrue(filename.endswith(".mp3"))


class TelegramManagerTests(unittest.TestCase):
    def test_async_telethon_operations_are_awaited(self) -> None:
        document = object()
        message = SimpleNamespace(id=42, media=SimpleNamespace(document=document))
        client = Mock()
        client.connect = AsyncMock()
        client.is_user_authorized = AsyncMock(return_value=True)
        client.is_connected.return_value = True
        client.send_file = AsyncMock(return_value=message)
        client.get_messages = AsyncMock(return_value=[message])
        client.delete_messages = AsyncMock()
        client.disconnect = Mock(return_value=None)

        with TemporaryDirectory() as directory:
            audio_path = Path(directory) / "track.mp3"
            audio_path.write_bytes(b"not-an-mp3")
            with patch(
                "yt_music_telegram_sync.telegram.TelegramClient",
                return_value=client,
            ):
                manager = TelegramManager(Path(directory) / "telegram", 1, "hash")
                manager.connect()
                uploaded_message, uploaded_document = manager.send_track(
                    audio_path,
                    Track(title="Title", artist="Artist"),
                )
                documents = manager.get_documents([42])
                manager.delete_message(42)
                manager.close()

        self.assertIs(uploaded_message, message)
        self.assertIs(uploaded_document, document)
        self.assertEqual(documents, {42: document})
        client.connect.assert_awaited_once_with()
        client.is_user_authorized.assert_awaited_once_with()
        client.send_file.assert_awaited_once()
        client.get_messages.assert_awaited_once_with("me", ids=[42])
        client.delete_messages.assert_awaited_once_with("me", 42)
        client.disconnect.assert_called_once_with()

    def test_playing_emoji_restores_previous_status(self) -> None:
        client, state, requests = self._emoji_client(
            premium=True,
            status=types.EmojiStatus(document_id=111),
        )
        with TemporaryDirectory() as directory:
            with patch(
                "yt_music_telegram_sync.telegram.TelegramClient",
                return_value=client,
            ):
                manager = TelegramManager(Path(directory) / "telegram", 1, "hash")
                self.assertTrue(manager.activate_playing_emoji(222))
                manager.restore_emoji_status()
                manager.close()

        self.assertEqual(
            [request.emoji_status.document_id for request in requests],
            [222, 111],
        )
        self.assertEqual(state["status"].document_id, 111)

    def test_manual_emoji_change_is_not_overwritten(self) -> None:
        client, state, requests = self._emoji_client(
            premium=True,
            status=types.EmojiStatus(document_id=111),
        )
        with TemporaryDirectory() as directory:
            with patch(
                "yt_music_telegram_sync.telegram.TelegramClient",
                return_value=client,
            ):
                manager = TelegramManager(Path(directory) / "telegram", 1, "hash")
                manager.activate_playing_emoji(222)
                state["status"] = types.EmojiStatus(document_id=333)
                manager.restore_emoji_status()
                manager.close()

        self.assertEqual(len(requests), 1)
        self.assertEqual(state["status"].document_id, 333)

    def test_playing_emoji_requires_premium(self) -> None:
        client, state, requests = self._emoji_client(
            premium=False,
            status=types.EmojiStatusEmpty(),
        )
        with TemporaryDirectory() as directory:
            with patch(
                "yt_music_telegram_sync.telegram.TelegramClient",
                return_value=client,
            ):
                manager = TelegramManager(Path(directory) / "telegram", 1, "hash")
                self.assertFalse(manager.activate_playing_emoji(222))
                manager.close()

        self.assertIsInstance(state["status"], types.EmojiStatusEmpty)
        self.assertEqual(requests, [])

    def test_personal_channel_restores_previous_channel(self) -> None:
        client, state, updates = self._personal_channel_client(channel_id=111)
        with TemporaryDirectory() as directory:
            with patch(
                "yt_music_telegram_sync.telegram.TelegramClient",
                return_value=client,
            ):
                manager = TelegramManager(Path(directory) / "telegram", 1, "hash")
                self.assertTrue(manager.activate_personal_channel(222))
                manager.restore_personal_channel()
                manager.close()

        self.assertEqual(updates, [222, 111])
        self.assertEqual(state["channel_id"], 111)

    def test_manual_personal_channel_change_is_not_overwritten(self) -> None:
        client, state, updates = self._personal_channel_client(channel_id=111)
        with TemporaryDirectory() as directory:
            with patch(
                "yt_music_telegram_sync.telegram.TelegramClient",
                return_value=client,
            ):
                manager = TelegramManager(Path(directory) / "telegram", 1, "hash")
                manager.activate_personal_channel(222)
                state["channel_id"] = 333
                manager.restore_personal_channel()
                manager.close()

        self.assertEqual(updates, [222])
        self.assertEqual(state["channel_id"], 333)

    def test_channel_message_operations_use_selected_channel(self) -> None:
        client, _state, _updates = self._personal_channel_client(channel_id=111)
        document = object()
        message = SimpleNamespace(id=8, media=SimpleNamespace(document=document))
        client.send_file = AsyncMock(return_value=message)
        client.get_messages = AsyncMock(return_value=[message])
        client.delete_messages = AsyncMock()
        with TemporaryDirectory() as directory:
            audio_path = Path(directory) / "track.mp3"
            audio_path.write_bytes(b"not-an-mp3")
            with patch(
                "yt_music_telegram_sync.telegram.TelegramClient",
                return_value=client,
            ):
                manager = TelegramManager(Path(directory) / "telegram", 1, "hash")
                manager.send_track(
                    audio_path,
                    Track("Title", "Artist"),
                    personal_channel_id=222,
                )
                manager.send_document(document, personal_channel_id=222)
                manager.get_documents([8], personal_channel_id=222)
                manager.delete_message(8, personal_channel_id=222)
                manager.close()

        sent_peer = client.send_file.await_args.args[0]
        fetched_peer = client.get_messages.await_args.args[0]
        deleted_peer = client.delete_messages.await_args.args[0]
        self.assertEqual(sent_peer.id, 222)
        self.assertEqual(client.send_file.await_count, 2)
        self.assertEqual(fetched_peer.id, 222)
        self.assertEqual(deleted_peer.id, 222)

    @staticmethod
    def _emoji_client(*, premium: bool, status):
        state = {"status": status}
        requests = []
        client = Mock()
        client.get_me = AsyncMock(
            side_effect=lambda: SimpleNamespace(
                premium=premium,
                emoji_status=state["status"],
            )
        )

        async def handle_request(request):
            if isinstance(request, functions.account.UpdateEmojiStatusRequest):
                requests.append(request)
                state["status"] = request.emoji_status
                return True
            raise AssertionError(type(request))

        client.side_effect = handle_request
        client.is_connected.return_value = True
        client.disconnect = Mock(return_value=None)
        return client, state, requests

    @staticmethod
    def _personal_channel_client(*, channel_id: int):
        state = {"channel_id": channel_id}
        updates: list[int] = []
        channels = [
            types.Channel(
                id=value,
                title=f"Channel {value}",
                photo=types.ChatPhotoEmpty(),
                date=None,
                broadcast=True,
                access_hash=value * 10,
            )
            for value in (111, 222, 333)
        ]
        client = Mock()

        async def handle_request(request):
            if isinstance(request, functions.users.GetFullUserRequest):
                return SimpleNamespace(
                    full_user=SimpleNamespace(
                        personal_channel_id=state["channel_id"]
                    )
                )
            if isinstance(
                request, functions.channels.GetAdminedPublicChannelsRequest
            ):
                return SimpleNamespace(chats=channels)
            if isinstance(request, functions.account.UpdatePersonalChannelRequest):
                selected = request.channel
                new_id = (
                    0
                    if isinstance(selected, types.InputChannelEmpty)
                    else selected.channel_id
                )
                updates.append(new_id)
                state["channel_id"] = new_id
                return True
            raise AssertionError(type(request))

        client.side_effect = handle_request
        client.is_connected.return_value = True
        client.disconnect = Mock(return_value=None)
        return client, state, updates


class TelegramEmojiStatusTests(unittest.TestCase):
    def test_collectible_status_is_converted_for_restoration(self) -> None:
        original = types.EmojiStatusCollectible(
            collectible_id=10,
            document_id=20,
            title="Gift",
            slug="gift",
            pattern_document_id=30,
            center_color=1,
            edge_color=2,
            pattern_color=3,
            text_color=4,
        )
        restored = _emoji_status_for_update(original)

        self.assertIsInstance(restored, types.InputEmojiStatusCollectible)
        self.assertEqual(restored.collectible_id, 10)


if __name__ == "__main__":
    unittest.main()
