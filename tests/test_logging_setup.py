import logging
import unittest

from yt_music_telegram_sync.logging_setup import _SecretRedactingFilter


class LoggingTests(unittest.TestCase):
    def test_redacts_lastfm_api_key_from_message(self) -> None:
        record = logging.LogRecord(
            "test",
            logging.INFO,
            __file__,
            1,
            "GET https://example.test/?api_key=secret&user=name",
            (),
            None,
        )
        self.assertTrue(_SecretRedactingFilter().filter(record))
        self.assertNotIn("secret", record.getMessage())
        self.assertIn("api_key=<redacted>", record.getMessage())


if __name__ == "__main__":
    unittest.main()
