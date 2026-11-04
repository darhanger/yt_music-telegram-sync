import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QLineEdit, QPushButton  # noqa: E402
from telethon import functions, types
from telethon.errors import SessionPasswordNeededError

from yt_music_telegram_sync.config import AppConfig
from yt_music_telegram_sync.setup_wizard import (
    SetupWizard,
    _telegram_capture_personal_channel,
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


class _ChannelSelectionClient:
    instances: ClassVar[list["_ChannelSelectionClient"]] = []

    def __init__(self, *_args) -> None:
        self.channel_id = 100
        self.disconnected = False
        self.channels = [
            types.Channel(
                id=value,
                title=f"Channel {value}",
                photo=types.ChatPhotoEmpty(),
                date=None,
                broadcast=True,
                access_hash=value * 10,
            )
            for value in (100, 200)
        ]
        self.__class__.instances.append(self)

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        self.disconnected = True

    async def is_user_authorized(self) -> bool:
        return True

    async def __call__(self, request):
        if isinstance(request, functions.users.GetFullUserRequest):
            return Mock(
                full_user=Mock(personal_channel_id=self.channel_id)
            )
        if isinstance(request, functions.channels.GetAdminedPublicChannelsRequest):
            return Mock(chats=self.channels)
        if isinstance(request, functions.account.UpdatePersonalChannelRequest):
            self.channel_id = (
                0
                if isinstance(request.channel, types.InputChannelEmpty)
                else request.channel.channel_id
            )
            return True
        raise AssertionError(type(request))

class TelegramSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        _TwoFactorClient.instances.clear()
        _EmojiSelectionClient.instances.clear()
        _ChannelSelectionClient.instances.clear()

    def test_code_and_2fa_password_use_same_connection(self) -> None:
        with patch(
            "yt_music_telegram_sync.setup_backend.TelegramClient", _TwoFactorClient
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
            "yt_music_telegram_sync.setup_backend.TelegramClient", _TwoFactorClient
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
                "yt_music_telegram_sync.setup_backend.TelegramClient",
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

    def test_channel_selection_restores_original_channel(self) -> None:
        def select_channel() -> bool:
            _ChannelSelectionClient.instances[0].channel_id = 200
            return True

        with patch(
                "yt_music_telegram_sync.setup_backend.TelegramClient",
            _ChannelSelectionClient,
        ):
            selected = asyncio.run(
                _telegram_capture_personal_channel(
                    Path("session"), 123, "hash", select_channel
                )
            )

        client = _ChannelSelectionClient.instances[0]
        self.assertEqual(selected, (200, "Channel 200"))
        self.assertEqual(client.channel_id, 100)
        self.assertTrue(client.disconnected)


class QtSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _wizard(self, directory: str, config: AppConfig) -> tuple[SetupWizard, Path, Path]:
        config_path = Path(directory) / "config.json"
        draft_path = Path(directory) / "config.draft.json"
        config.save(config_path)
        return SetupWizard(config_path), config_path, draft_path

    def test_dialog_event_loop_returns_cancel_result(self) -> None:
        config = AppConfig(
            lastfm_username="user",
            lastfm_api_key="key",
            telegram_api_id=123,
            telegram_api_hash="hash",
        )
        with tempfile.TemporaryDirectory() as directory:
            wizard, _, _ = self._wizard(directory, config)
            QTimer.singleShot(0, wizard._cancel)
            self.assertFalse(wizard.run())

    def test_designer_form_saves_settings_and_language_theme(self) -> None:
        config = AppConfig(
            lastfm_username="user",
            lastfm_api_key="key",
            telegram_api_id=123,
            telegram_api_hash="hash",
        )
        with tempfile.TemporaryDirectory() as directory:
            wizard, config_path, draft_path = self._wizard(directory, config)
            self.assertEqual(
                wizard._widget("titleLabel", QLabel).text(),
                "♫  YT Music → Telegram",
            )
            wizard._widget("downloadWorkersEdit", QLineEdit).setText("3")
            wizard._widget("notificationsEnabledCheck", QCheckBox).setChecked(False)
            wizard.language_combo.setCurrentIndex(wizard.language_combo.findData("en"))
            wizard.dark_mode.setChecked(False)
            with patch(
                "yt_music_telegram_sync.setup_wizard.default_draft_config_path",
                return_value=draft_path,
            ):
                wizard._save()
            loaded = AppConfig.load(config_path)
        self.assertTrue(wizard.saved)
        self.assertEqual(loaded.download_workers, 3)
        self.assertFalse(loaded.notifications_enabled)
        self.assertEqual(loaded.ui_language, "en")
        self.assertEqual(loaded.ui_theme, "light")

    def test_window_close_saves_valid_changes(self) -> None:
        config = AppConfig(
            lastfm_username="user",
            lastfm_api_key="key",
            telegram_api_id=123,
            telegram_api_hash="hash",
        )
        with tempfile.TemporaryDirectory() as directory:
            wizard, config_path, draft_path = self._wizard(directory, config)
            wizard._widget("cacheSizeEdit", QLineEdit).setText("37")
            with patch(
                "yt_music_telegram_sync.setup_wizard.default_draft_config_path",
                return_value=draft_path,
            ):
                wizard.root.close()
            loaded = AppConfig.load(config_path)
        self.assertTrue(wizard.saved)
        self.assertEqual(loaded.cache_size, 37)

    def test_cancel_does_not_save(self) -> None:
        config = AppConfig(
            lastfm_username="user",
            lastfm_api_key="key",
            telegram_api_id=123,
            telegram_api_hash="hash",
        )
        with tempfile.TemporaryDirectory() as directory:
            wizard, config_path, _ = self._wizard(directory, config)
            wizard._widget("cacheSizeEdit", QLineEdit).setText("37")
            wizard._cancel()
            loaded = AppConfig.load(config_path)
        self.assertFalse(wizard.saved)
        self.assertEqual(loaded.cache_size, 20)

    def test_mode_and_emoji_toggle_controls(self) -> None:
        config = AppConfig(
            lastfm_username="user",
            lastfm_api_key="key",
            telegram_api_id=123,
            telegram_api_hash="hash",
        )
        with tempfile.TemporaryDirectory() as directory:
            wizard, _, _ = self._wizard(directory, config)
            wizard.output_mode.setCurrentIndex(
                wizard.output_mode.findData("profile_and_channel")
            )
            self.assertTrue(wizard._widget("personalChannelEdit", QLineEdit).isEnabled())
            self.assertTrue(wizard._widget("removeWhenIdleCheck", QCheckBox).isEnabled())
            wizard.output_mode.setCurrentIndex(
                wizard.output_mode.findData("personal_channel")
            )
            self.assertFalse(wizard._widget("removeWhenIdleCheck", QCheckBox).isEnabled())
            self.assertFalse(wizard._widget("playingEmojiEdit", QLineEdit).isEnabled())
            wizard._widget("emojiEnabledCheck", QCheckBox).setChecked(True)
            self.assertTrue(wizard._widget("playingEmojiEdit", QLineEdit).isEnabled())
            self.assertTrue(wizard._widget("selectEmojiButton", QPushButton).isEnabled())
            wizard._cancel()

    def test_success_status_uses_green_indicator(self) -> None:
        config = AppConfig(
            lastfm_username="user",
            lastfm_api_key="key",
            telegram_api_id=123,
            telegram_api_hash="hash",
        )
        with tempfile.TemporaryDirectory() as directory:
            wizard, _, _ = self._wizard(directory, config)
            wizard._set_status("Authorized", "success")
            self.assertEqual(wizard._widget("statusLabel", QLabel).text(), "Authorized")
            self.assertIn("#68d391", wizard._widget("statusIndicator", QLabel).styleSheet())
            wizard._cancel()


if __name__ == "__main__":
    unittest.main()
