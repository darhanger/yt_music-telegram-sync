import tempfile
import unittest
from pathlib import Path

from yt_music_telegram_sync.config import AppConfig, ConfigurationError


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

    @staticmethod
    def _valid_config() -> AppConfig:
        return AppConfig(
            lastfm_username="user",
            lastfm_api_key="key",
            telegram_api_id=123,
            telegram_api_hash="hash",
        )


if __name__ == "__main__":
    unittest.main()
