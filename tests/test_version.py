import unittest
from importlib.metadata import version

from yt_music_telegram_sync import __version__


class VersionTests(unittest.TestCase):
    def test_package_metadata_matches_application_version(self) -> None:
        self.assertEqual(version("yt-music-telegram-sync"), __version__)


if __name__ == "__main__":
    unittest.main()
