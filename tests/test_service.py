import unittest
from unittest.mock import Mock

from yt_music_telegram_sync.config import AppConfig
from yt_music_telegram_sync.lastfm import LastFmError
from yt_music_telegram_sync.service import SyncApplicationService


class SyncApplicationServiceTests(unittest.TestCase):
    def test_idle_cleanup_runs_once_until_a_track_appears(self) -> None:
        config = self._config()
        config.absent_confirmations = 2
        service = SyncApplicationService(config)
        lastfm = Mock()
        lastfm.get_now_playing.side_effect = [None, None, None, None]
        sync = Mock()
        waits = 0

        def wait(_timeout: float) -> None:
            nonlocal waits
            waits += 1
            if waits == 4:
                service._stop_event.set()

        service._wait = wait  # type: ignore[method-assign]

        service._poll_loop(lastfm, sync)

        sync.handle_no_track.assert_called_once_with(config.remove_when_idle)
        self.assertEqual(lastfm.get_now_playing.call_count, 4)
        self.assertEqual(service.status.kind, "idle")

    def test_permanent_lastfm_error_stops_automatic_retries(self) -> None:
        service = SyncApplicationService(self._config())
        lastfm = Mock()
        lastfm.get_now_playing.side_effect = LastFmError(
            "Invalid API key",
            code=10,
        )
        sync = Mock()
        service._wait = Mock()  # type: ignore[method-assign]

        service._poll_loop(lastfm, sync)

        self.assertEqual(lastfm.get_now_playing.call_count, 1)
        service._wait.assert_not_called()
        self.assertEqual(service.status.kind, "error")

    def test_stop_reports_when_worker_does_not_finish_in_time(self) -> None:
        service = SyncApplicationService(self._config())
        thread = Mock()
        thread.is_alive.return_value = True
        service._thread = thread

        stopped = service.stop(timeout=0.01)

        self.assertFalse(stopped)
        thread.join.assert_called_once_with(timeout=0.01)

    @staticmethod
    def _config() -> AppConfig:
        return AppConfig(
            lastfm_username="user",
            lastfm_api_key="key",
            telegram_api_id=123,
            telegram_api_hash="hash",
            poll_interval_seconds=3,
            notifications_enabled=False,
            notification_sound_enabled=False,
            ui_language="en",
        )


if __name__ == "__main__":
    unittest.main()
