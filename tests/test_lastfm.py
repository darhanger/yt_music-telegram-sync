import json
import unittest

import httpx

from yt_music_telegram_sync.lastfm import LastFmClient, LastFmError


class LastFmClientTests(unittest.TestCase):
    def test_parses_now_playing_track(self) -> None:
        payload = {
            "recenttracks": {
                "track": [
                    {
                        "name": "Track",
                        "artist": {"#text": "Artist"},
                        "album": {"#text": "Album"},
                        "mbid": "track-id",
                        "url": "https://last.fm/track",
                        "image": [
                            {"#text": "https://img/small.jpg", "size": "small"},
                            {"#text": "https://img/large.jpg", "size": "large"},
                        ],
                        "@attr": {"nowplaying": "true"},
                    }
                ]
            }
        }
        client = self._client(payload)
        try:
            track = client.get_now_playing()
        finally:
            client.close()
        self.assertIsNotNone(track)
        assert track is not None
        self.assertEqual(track.title, "Track")
        self.assertEqual(track.artist, "Artist")
        self.assertEqual(track.album, "Album")
        self.assertEqual(track.cover_url, "https://img/large.jpg")

    def test_returns_none_for_completed_scrobble(self) -> None:
        payload = {
            "recenttracks": {
                "track": [
                    {
                        "name": "Track",
                        "artist": {"#text": "Artist"},
                        "album": {"#text": "Album"},
                        "@attr": {},
                    }
                ]
            }
        }
        client = self._client(payload)
        try:
            self.assertIsNone(client.get_now_playing())
        finally:
            client.close()

    def test_raises_typed_api_error(self) -> None:
        client = self._client({"error": 29, "message": "Rate limit exceeded"})
        try:
            with self.assertRaises(LastFmError) as context:
                client.get_now_playing()
        finally:
            client.close()
        self.assertEqual(context.exception.code, 29)
        self.assertTrue(context.exception.is_transient)

    def test_network_error_does_not_expose_api_key(self) -> None:
        secret = "private-api-key"

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection failed", request=request)

        client = LastFmClient(secret, "user", transport=httpx.MockTransport(handler))
        try:
            with self.assertRaises(LastFmError) as context:
                client.get_now_playing()
        finally:
            client.close()
        self.assertNotIn(secret, str(context.exception))

    @staticmethod
    def _client(payload: dict) -> LastFmClient:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=json.dumps(payload).encode("utf-8"))

        return LastFmClient("api-key", "user", transport=httpx.MockTransport(handler))


if __name__ == "__main__":
    unittest.main()
