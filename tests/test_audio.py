import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

from yt_music_telegram_sync.audio import ArtworkLoader, YtDlpBackend
from yt_music_telegram_sync.models import Track


class YtDlpBackendTests(unittest.TestCase):
    def test_cancelled_download_does_not_create_a_file(self) -> None:
        cancelled = threading.Event()
        cancelled.set()
        backend = YtDlpBackend(Mock(), cancel_event=cancelled)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "track.mp3"

            created = backend.create(destination, Track("Title", "Artist"))

            self.assertFalse(created)
            self.assertFalse(destination.exists())


class ArtworkLoaderTests(unittest.TestCase):
    def test_streaming_download_stops_when_size_limit_is_exceeded(self) -> None:
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "image/jpeg"},
                content=b"12345",
            )
        )
        loader = ArtworkLoader(transport=transport)

        try:
            with patch("yt_music_telegram_sync.audio._MAX_ARTWORK_BYTES", 4):
                artwork = loader.get("https://example.test/cover.jpg")
        finally:
            loader.close()

        self.assertIsNone(artwork)


if __name__ == "__main__":
    unittest.main()
