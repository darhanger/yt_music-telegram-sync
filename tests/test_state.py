import json
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

    def test_entries_are_isolated_by_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "state.json")
            profile = [StoredTrack(Track("Profile", "Artist"), 3)]
            channel = [StoredTrack(Track("Channel", "Artist"), 7, 8)]
            store.save(profile, destination="profile_music")
            store.save(channel, destination="profile_and_channel:123")

            self.assertEqual(
                store.load(destination="profile_and_channel:123"), channel
            )
            self.assertEqual(store.load(destination="profile_music"), profile)
            self.assertEqual(store.load(destination="personal_channel:456"), [])

    def test_loads_legacy_profile_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "tracks": [
                            {
                                "track": {"title": "Title", "artist": "Artist"},
                                "message_id": 42,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            store = StateStore(path)

            self.assertEqual(
                store.load(),
                [StoredTrack(Track("Title", "Artist"), 42)],
            )


if __name__ == "__main__":
    unittest.main()
