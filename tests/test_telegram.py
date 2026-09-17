import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from yt_music_telegram_sync.models import Track
from yt_music_telegram_sync.telegram import TelegramManager, _track_filename


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


if __name__ == "__main__":
    unittest.main()
