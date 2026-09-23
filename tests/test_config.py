import json
import tempfile
import unittest
from pathlib import Path

from yt_music_telegram_sync.config import (
    AppConfig,
    ConfigurationError,
    load_partial,
)


class ConfigTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            config = self._valid_config()
            config.save(path)
            loaded = AppConfig.load(path)
        self.assertEqual(loaded, config)

    def test_rejects_too_frequent_polling(self) -> None:
        config = self._valid_config()
        config.poll_interval_seconds = 1
        with self.assertRaises(ConfigurationError):
            config.validate()

    def test_existing_config_defaults_to_russian(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "lastfm_username": "user",
                        "lastfm_api_key": "key",
                        "telegram_api_id": 123,
                        "telegram_api_hash": "hash",
                    }
                ),
                encoding="utf-8",
            )

            loaded = AppConfig.load(path)

        self.assertEqual(loaded.ui_language, "ru")

    def test_rejects_negative_emoji_status_id(self) -> None:
        config = self._valid_config()
        config.telegram_playing_emoji_id = -1
        with self.assertRaises(ConfigurationError):
            config.validate()

    def test_personal_channel_mode_requires_channel_id(self) -> None:
        config = self._valid_config()
        config.telegram_output_mode = "personal_channel"
        config.telegram_personal_channel_id = 0

        with self.assertRaises(ConfigurationError):
            config.validate()

        config.telegram_personal_channel_id = 123
        config.validate()

        config.telegram_output_mode = "profile_and_channel"
        config.validate()
        config.telegram_personal_channel_id = 0
        with self.assertRaises(ConfigurationError):
            config.validate()

    def test_enabled_emoji_requires_selected_status(self) -> None:
        config = self._valid_config()
        config.telegram_playing_emoji_enabled = True
        config.telegram_playing_emoji_id = 0

        with self.assertRaises(ConfigurationError):
            config.validate()

    def test_existing_emoji_setting_is_migrated_to_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "lastfm_username": "user",
                        "lastfm_api_key": "key",
                        "telegram_api_id": 123,
                        "telegram_api_hash": "hash",
                        "telegram_playing_emoji_id": 777,
                    }
                ),
                encoding="utf-8",
            )

            loaded = AppConfig.load(path)

        self.assertTrue(loaded.telegram_playing_emoji_enabled)
        self.assertEqual(loaded.telegram_playing_emoji_id, 777)

    def test_validation_errors_use_selected_language(self) -> None:
        config = self._valid_config()
        config.ui_language = "en"
        config.poll_interval_seconds = 1

        with self.assertRaisesRegex(
            ConfigurationError,
            "cannot be shorter than 3 seconds",
        ):
            config.validate()

    def test_rejects_unknown_interface_language(self) -> None:
        config = self._valid_config()
        config.ui_language = "de"

        with self.assertRaises(ConfigurationError):
            config.validate()

    def test_rejects_unknown_interface_theme(self) -> None:
        config = self._valid_config()
        config.ui_theme = "neon"

        with self.assertRaises(ConfigurationError):
            config.validate()

    def test_rejects_non_object_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("[]", encoding="utf-8")

            with self.assertRaises(ConfigurationError):
                AppConfig.load(path)

    def test_invalid_field_type_is_reported_as_configuration_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            payload = {
                "lastfm_username": "user",
                "lastfm_api_key": "key",
                "telegram_api_id": 123,
                "telegram_api_hash": "hash",
                "poll_interval_seconds": "fast",
            }
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(ConfigurationError):
                AppConfig.load(path)

    def test_partial_load_ignores_non_object_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("[]", encoding="utf-8")

            loaded = load_partial(path)

        self.assertEqual(loaded, AppConfig())

    @staticmethod
    def _valid_config() -> AppConfig:
        return AppConfig(
            lastfm_username="user",
            lastfm_api_key="key",
            telegram_api_id=123,
            telegram_api_hash="hash",
            telegram_playing_emoji_id=777,
            notifications_enabled=False,
            notification_sound_enabled=False,
            ui_language="en",
        )


if __name__ == "__main__":
    unittest.main()
