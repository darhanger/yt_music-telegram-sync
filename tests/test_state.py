import tempfile
import unittest
from pathlib import Path

from yt_music_telegram_sync.models import Track
from yt_music_telegram_sync.state import StateStore, StoredTrack


class StateStoreTests(unittest.TestCase):
    def test_round_trip_and_skips_invalid_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = StateStore(path)
            expected = [StoredTrack(Track("Title", "Artist", "Album"), 42)]
            store.save(expected)
            actual = store.load()
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
