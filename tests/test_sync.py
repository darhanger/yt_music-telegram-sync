import unittest
from dataclasses import dataclass
from pathlib import Path

from yt_music_telegram_sync.models import Track
from yt_music_telegram_sync.sync import CachedTrack, TrackSyncService
from yt_music_telegram_sync.telegram import TelegramError


class FakeBackend:
    def create(self, destination: Path, _track: Track) -> bool:
        destination.write_bytes(b"fake-mp3")
        return True


@dataclass
class FakeMessage:
    id: int


class FakeTelegram:
    def __init__(self) -> None:
        self.next_id = 1
        self.saved: list[tuple[int, bool]] = []
        self.deleted: list[int] = []
        self.unsave_failures: set[int] = set()

    def send_track(self, _path: Path, _track: Track):
        message = FakeMessage(self.next_id)
        self.next_id += 1
        return message, message.id

    def save_music(self, document, *, unsave: bool, after=None) -> None:
        self.saved.append((document, unsave))
        if unsave and document in self.unsave_failures:
            raise TelegramError("temporary failure")

    def delete_message(self, message_id: int) -> None:
        self.deleted.append(message_id)


class TrackSyncTests(unittest.TestCase):
    def test_restored_track_is_reused(self) -> None:
        telegram = FakeTelegram()
        backend = FakeBackend()
        track = Track("One", "Artist")
        restored = CachedTrack(track=track, message_id=50, document=500)
        service = TrackSyncService(
            telegram,  # type: ignore[arg-type]
            backend,
            backend,  # type: ignore[arg-type]
            cache_size=2,
            initial_entries=[restored],
        )
        try:
            service.handle_track(track)
        finally:
            service.close()
        self.assertEqual(telegram.next_id, 1)
        self.assertEqual(telegram.saved, [(500, True), (500, False)])

    def test_duplicate_is_reused_and_oldest_is_evicted(self) -> None:
        telegram = FakeTelegram()
        backend = FakeBackend()
        service = TrackSyncService(
            telegram,  # type: ignore[arg-type]
            backend,
            backend,  # type: ignore[arg-type]
            cache_size=2,
        )
        one = Track("One", "Artist")
        two = Track("Two", "Artist")
        three = Track("Three", "Artist")
        try:
            service.handle_track(one)
            service.handle_track(two)
            service.handle_track(one)
            self.assertEqual(telegram.next_id, 3)
            service.handle_track(three)
        finally:
            service.close()
        self.assertIn(2, telegram.deleted)
        self.assertNotIn(1, telegram.deleted)

    def test_idle_cleanup_removes_all_tracks_from_listening_session(self) -> None:
        telegram = FakeTelegram()
        backend = FakeBackend()
        changes: list[list[int]] = []
        service = TrackSyncService(
            telegram,  # type: ignore[arg-type]
            backend,
            backend,  # type: ignore[arg-type]
            cache_size=3,
            cache_changed=lambda entries: changes.append(
                [entry.message_id for entry in entries]
            ),
        )
        try:
            service.handle_track(Track("One", "Artist"))
            service.handle_track(Track("Two", "Artist"))
            service.handle_no_track(remove_when_idle=True)
        finally:
            service.close()

        self.assertIsNone(service.active_track)
        self.assertEqual(telegram.deleted, [1, 2])
        self.assertEqual(changes[-1], [])

    def test_failed_cleanup_keeps_track_for_retry(self) -> None:
        telegram = FakeTelegram()
        backend = FakeBackend()
        changes: list[list[int]] = []
        service = TrackSyncService(
            telegram,  # type: ignore[arg-type]
            backend,
            backend,  # type: ignore[arg-type]
            cache_size=1,
            cache_changed=lambda entries: changes.append(
                [entry.message_id for entry in entries]
            ),
        )
        try:
            service.handle_track(Track("One", "Artist"))
            telegram.unsave_failures.add(1)
            with self.assertLogs(
                "yt_music_telegram_sync.sync", level="ERROR"
            ) as captured_logs:
                with self.assertRaises(TelegramError):
                    service.clear()
            self.assertTrue(captured_logs.output)
            self.assertEqual(changes[-1], [1])
            self.assertEqual(telegram.deleted, [])

            telegram.unsave_failures.clear()
            service.clear()
        finally:
            service.close()

        self.assertEqual(telegram.deleted, [1])
        self.assertEqual(changes[-1], [])


if __name__ == "__main__":
    unittest.main()
