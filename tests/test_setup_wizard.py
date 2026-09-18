import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import Mock, patch

from telethon import functions, types
from telethon.errors import SessionPasswordNeededError

from yt_music_telegram_sync.config import AppConfig
from yt_music_telegram_sync.setup_wizard import (
    SetupWizard,
    _telegram_capture_playing_emoji,
    _telegram_sign_in,
)


class _TwoFactorClient:
    instances: ClassVar[list["_TwoFactorClient"]] = []

    def __init__(self, *_args) -> None:
        self.sign_in_calls: list[dict] = []
        self.disconnected = False
        self.__class__.instances.append(self)

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        self.disconnected = True

    async def is_user_authorized(self) -> bool:
        return False

    async def sign_in(self, **kwargs) -> None:
        self.sign_in_calls.append(kwargs)
        if "code" in kwargs:
            raise SessionPasswordNeededError(request=None)


class _EmojiSelectionClient:
    instances: ClassVar[list["_EmojiSelectionClient"]] = []
    premium = True

    def __init__(self, *_args) -> None:
        self.status = types.EmojiStatus(document_id=100)
        self.disconnected = False
        self.__class__.instances.append(self)

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        self.disconnected = True

    async def is_user_authorized(self) -> bool:
        return True

    async def get_me(self):
        return Mock(premium=self.premium, emoji_status=self.status)

    async def __call__(self, request):
        if not isinstance(request, functions.account.UpdateEmojiStatusRequest):
            raise AssertionError(type(request))
        self.status = request.emoji_status
        return True


class TelegramSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        _TwoFactorClient.instances.clear()
        _EmojiSelectionClient.instances.clear()

    def test_code_and_2fa_password_use_same_connection(self) -> None:
        with patch(
            "yt_music_telegram_sync.setup_wizard.TelegramClient", _TwoFactorClient
        ):
            needs_password = asyncio.run(
                _telegram_sign_in(
                    Path("session"),
                    123,
                    "hash",
                    "+10000000000",
                    "12345",
                    "code-hash",
                    "",
                    lambda: "secret",
                )
            )

        self.assertFalse(needs_password)
        self.assertEqual(len(_TwoFactorClient.instances), 1)
        client = _TwoFactorClient.instances[0]
        self.assertEqual(client.sign_in_calls[0]["code"], "12345")
        self.assertEqual(client.sign_in_calls[1], {"password": "secret"})
        self.assertTrue(client.disconnected)

    def test_cancelled_2fa_reports_that_new_code_is_required(self) -> None:
        with patch(
            "yt_music_telegram_sync.setup_wizard.TelegramClient", _TwoFactorClient
        ):
            needs_password = asyncio.run(
                _telegram_sign_in(
                    Path("session"),
                    123,
                    "hash",
                    "+10000000000",
                    "12345",
                    "code-hash",
                    "",
                    lambda: None,
                )
            )

        self.assertTrue(needs_password)
        self.assertEqual(len(_TwoFactorClient.instances[0].sign_in_calls), 1)

    def test_emoji_selection_restores_original_status(self) -> None:
        def select_emoji() -> bool:
            _EmojiSelectionClient.instances[0].status = types.EmojiStatus(
                document_id=200
            )
            return True

        with patch(
            "yt_music_telegram_sync.setup_wizard.TelegramClient",
            _EmojiSelectionClient,
        ):
            document_id = asyncio.run(
                _telegram_capture_playing_emoji(
                    Path("session"), 123, "hash", select_emoji
                )
            )

        client = _EmojiSelectionClient.instances[0]
        self.assertEqual(document_id, 200)
        self.assertEqual(client.status.document_id, 100)
        self.assertTrue(client.disconnected)


class SetupPersistenceTests(unittest.TestCase):
    def test_save_persists_local_settings_without_network_checks(self) -> None:
        config = AppConfig(
            lastfm_username="user",
            lastfm_api_key="key",
            telegram_api_id=123,
            telegram_api_hash="hash",
            audio_mode="mixed",
            download_workers=3,
            notifications_enabled=False,
            notification_sound_enabled=False,
            ui_language="en",
        )
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            draft_path = Path(directory) / "config.draft.json"
            draft_path.touch()
            wizard, root = self._wizard(config_path, config)

            with patch(
                "yt_music_telegram_sync.setup_wizard.default_draft_config_path",
                return_value=draft_path,
            ):
                wizard._save()

            loaded = AppConfig.load(config_path)

        self.assertEqual(loaded.audio_mode, "mixed")
        self.assertEqual(loaded.download_workers, 3)
        self.assertFalse(loaded.notifications_enabled)
        self.assertFalse(loaded.notification_sound_enabled)
        self.assertEqual(loaded.ui_language, "en")
        self.assertTrue(wizard.saved)
        root.destroy.assert_called_once_with()

    def test_window_close_saves_valid_changes(self) -> None:
        config = AppConfig(
            lastfm_username="user",
            lastfm_api_key="key",
            telegram_api_id=123,
            telegram_api_hash="hash",
            audio_mode="audio",
        )
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            draft_path = Path(directory) / "config.draft.json"
            wizard, root = self._wizard(config_path, config)

            with patch(
                "yt_music_telegram_sync.setup_wizard.default_draft_config_path",
                return_value=draft_path,
            ):
                wizard._close()

            loaded = AppConfig.load(config_path)

        self.assertEqual(loaded.audio_mode, "audio")
        self.assertTrue(wizard.saved)
        root.destroy.assert_called_once_with()

    @staticmethod
    def _wizard(config_path: Path, config: AppConfig) -> tuple[SetupWizard, Mock]:
        wizard = object.__new__(SetupWizard)
        root = Mock()
        wizard.config_path = config_path
        wizard.saved = False
        wizard.status = Mock()
        wizard.ui_language = Mock()
        wizard.ui_language.get.return_value = config.ui_language
        wizard.root = root
        wizard._config_from_form = Mock(  # type: ignore[method-assign]
            return_value=config
        )
        return wizard, root


if __name__ == "__main__":
    unittest.main()
