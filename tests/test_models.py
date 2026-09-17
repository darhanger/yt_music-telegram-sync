import unittest

from yt_music_telegram_sync.models import Track


class TrackTests(unittest.TestCase):
    def test_metadata_identity_is_normalized(self) -> None:
        first = Track(title="  My   Song ", artist="Björk", album="Album")
        second = Track(title="my song", artist="BJÖRK", album="album")
        self.assertEqual(first.identity, second.identity)

    def test_mbid_takes_precedence(self) -> None:
        first = Track(title="One", artist="Artist", mbid="ABC")
        second = Track(title="Other", artist="Other", mbid="abc")
        self.assertEqual(first.identity, second.identity)


if __name__ == "__main__":
    unittest.main()
