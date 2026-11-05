import unittest

from yt_music_telegram_sync.models import Track


class TrackTests(unittest.TestCase):
    def test_metadata_identity_is_normalized(self) -> None:
        first = Track(title="  My   Song ", artist="Björk", album="Album")
        second = Track(title="my song", artist="BJÖRK", album="album")
        self.assertEqual(first.identity, second.identity)

    def test_album_and_mbid_do_not_split_same_song(self) -> None:
        first = Track(title="One", artist="Artist", album="Album", mbid="ABC")
        second = Track(title="One", artist="Artist", album="Other", mbid="XYZ")
        self.assertEqual(first.identity, second.identity)

    def test_mbid_does_not_merge_different_songs(self) -> None:
        first = Track(title="One", artist="Artist", mbid="ABC")
        second = Track(title="Other", artist="Artist", mbid="ABC")
        self.assertNotEqual(first.identity, second.identity)


if __name__ == "__main__":
    unittest.main()
