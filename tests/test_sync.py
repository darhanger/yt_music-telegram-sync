import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

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
        self.activated_emojis: list[int] = []
        self.emoji_active = False
        self.emoji_restore_count = 0
        self.sent_to_channels: list[int] = []
        self.deleted_from_channels: list[tuple[int, int]] = []
        self.activated_channels: list[int] = []
        self.channel_active = False
        self.channel_restore_count = 0

    def send_track(
        self, _path: Path, _track: Track, *, personal_channel_id: int = 0
    ):
        message = FakeMessage(self.next_id)
        self.next_id += 1
        if personal_channel_id:
            self.sent_to_channels.append(personal_channel_id)
        return message, message.id

    def send_document(self, document, *, personal_channel_id: int):
        message = FakeMessage(self.next_id)
        self.next_id += 1
        self.sent_to_channels.append(personal_channel_id)
        return message, document

    def save_music(self, document, *, unsave: bool, after=None) -> None:
        self.saved.append((document, unsave))
        if unsave and document in self.unsave_failures:
            raise TelegramError("temporary failure")

    def delete_message(
        self, message_id: int, *, personal_channel_id: int = 0
    ) -> None:
        self.deleted.append(message_id)
        if personal_channel_id:
            self.deleted_from_channels.append((message_id, personal_channel_id))

    def activate_playing_emoji(self, document_id: int) -> bool:
        if not self.emoji_active:
            self.activated_emojis.append(document_id)
            self.emoji_active = True
        return True

    def restore_emoji_status(self) -> None:
        if self.emoji_active:
            self.emoji_active = False
            self.emoji_restore_count += 1

    def activate_personal_channel(self, channel_id: int) -> bool:
        if not self.channel_active:
            self.activated_channels.append(channel_id)
            self.channel_active = True
        return True

    def restore_personal_channel(self) -> None:
        if self.channel_active:
            self.channel_active = False
            self.channel_restore_count += 1


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

    def test_emoji_status_follows_scrobbling_lifecycle(self) -> None:
        telegram = FakeTelegram()
        backend = FakeBackend()
        service = TrackSyncService(
            telegram,  # type: ignore[arg-type]
            backend,
            backend,  # type: ignore[arg-type]
            cache_size=1,
            playing_emoji_id=777,
        )
        try:
            service.handle_scrobbling_active()
            service.handle_scrobbling_active()
            service.handle_no_track(remove_when_idle=False)
        finally:
            service.close()

        self.assertEqual(telegram.activated_emojis, [777])
        self.assertEqual(telegram.emoji_restore_count, 1)

    def test_personal_channel_keeps_only_current_post_and_restores_profile(self) -> None:
        telegram = FakeTelegram()
        backend = FakeBackend()
        service = TrackSyncService(
            telegram,  # type: ignore[arg-type]
            backend,
            backend,  # type: ignore[arg-type]
            cache_size=20,
            playing_emoji_id=777,
            personal_channel_id=900,
            profile_music_enabled=False,
        )
        try:
            service.handle_scrobbling_active()
            service.handle_scrobbling_active()
            service.handle_track(Track("One", "Artist"))
            service.handle_track(Track("Two", "Artist"))
            service.handle_no_track(remove_when_idle=False)
        finally:
            service.close()

        self.assertEqual(telegram.activated_channels, [900])
        self.assertEqual(telegram.channel_restore_count, 1)
        self.assertEqual(telegram.sent_to_channels, [900, 900])
        self.assertEqual(
            telegram.deleted_from_channels,
            [(1, 900), (2, 900)],
        )
        self.assertEqual(telegram.saved, [])
        self.assertEqual(telegram.activated_emojis, [777])
        self.assertEqual(telegram.emoji_restore_count, 1)

    def test_personal_channel_post_is_removed_on_close(self) -> None:
        telegram = FakeTelegram()
        backend = FakeBackend()
        service = TrackSyncService(
            telegram,  # type: ignore[arg-type]
            backend,
            backend,  # type: ignore[arg-type]
            cache_size=20,
            personal_channel_id=900,
            profile_music_enabled=False,
        )
        service.handle_scrobbling_active()
        service.handle_track(Track("One", "Artist"))

        service.close()

        self.assertEqual(telegram.deleted_from_channels, [(1, 900)])
        self.assertEqual(telegram.channel_restore_count, 1)

    def test_combined_mode_keeps_profile_music_and_clears_channel_post(self) -> None:
        telegram = FakeTelegram()
        backend = FakeBackend()
        service = TrackSyncService(
            telegram,  # type: ignore[arg-type]
            backend,
            backend,  # type: ignore[arg-type]
            cache_size=3,
            playing_emoji_id=777,
            personal_channel_id=900,
            profile_music_enabled=True,
        )
        try:
            service.handle_scrobbling_active()
            one = Track("One", "Artist")
            service.handle_track(one)
            service.handle_track(Track("Two", "Artist"))
            service.handle_track(one)
            service.handle_no_track(remove_when_idle=False)
        finally:
            service.close()

        self.assertEqual(telegram.sent_to_channels, [900, 900, 900])
        self.assertEqual(
            telegram.deleted_from_channels,
            [(2, 900), (4, 900), (5, 900)],
        )
        self.assertEqual(
            telegram.saved,
            [(1, False), (3, False), (1, True), (1, False)],
        )
        self.assertEqual(telegram.activated_emojis, [777])
        self.assertEqual(telegram.emoji_restore_count, 1)
        self.assertEqual(telegram.channel_restore_count, 1)

    def test_combined_mode_replaces_profile_and_current_channel_post(self) -> None:
        telegram = FakeTelegram()
        telegram.next_id = 3
        backend = FakeBackend()
        track = Track("One", "Artist")
        entry = CachedTrack(
            track=track,
            message_id=1,
            document=1,
            channel_message_id=2,
        )
        service = TrackSyncService(
            telegram,  # type: ignore[arg-type]
            backend,
            backend,  # type: ignore[arg-type]
            cache_size=3,
            personal_channel_id=900,
            profile_music_enabled=True,
            initial_entries=[entry],
        )
        try:
            with TemporaryDirectory() as directory:
                replacement = Path(directory) / "replacement.mp3"
                replacement.write_bytes(b"replacement")
                entry.replacement_path = replacement
                service._apply_replacement(entry)

            self.assertEqual(entry.message_id, 3)
            self.assertEqual(entry.channel_message_id, 4)
            self.assertEqual(telegram.saved, [(3, False), (1, True)])
            self.assertEqual(telegram.deleted_from_channels, [(2, 900)])
            self.assertIn(1, telegram.deleted)
        finally:
            service.close()


if __name__ == "__main__":
    unittest.main()
