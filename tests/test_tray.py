import os
import threading
import unittest
from pathlib import Path
from unittest.mock import ANY, Mock, patch

from PIL import Image

from yt_music_telegram_sync.tray import TrayController, _NotificationIcon


class TraySettingsLifecycleTests(unittest.TestCase):
    def _controller(
        self, process: Mock
    ) -> tuple[TrayController, Mock, Mock, Mock]:
        controller = object.__new__(TrayController)
        service = Mock()
        icon = Mock()
        notify = Mock()
        controller.service = service
        controller._config_path = Path("custom-config.json")
        controller._setup_lock = threading.Lock()
        controller._setup_process = process
        controller.icon = icon
        controller._notify = notify  # type: ignore[method-assign]
        return controller, service, icon, notify

    def test_saved_settings_restart_tray_with_same_config(self) -> None:
        setup_process = Mock()
        setup_process.wait.return_value = 0
        controller, service, icon, _ = self._controller(setup_process)

        with patch("yt_music_telegram_sync.tray.subprocess.Popen") as popen:
            controller._finish_setup(setup_process)

        service.stop.assert_called_once_with()
        popen.assert_called_once_with(
            [
                ANY,
                "-m",
                "yt_music_telegram_sync",
                "--tray",
                "--restart-wait",
                "--config",
                "custom-config.json",
            ],
            close_fds=True,
        )
        icon.stop.assert_called_once_with()
        self.assertIsNone(controller._setup_process)

    def test_cancelled_settings_resume_existing_service(self) -> None:
        setup_process = Mock()
        setup_process.wait.return_value = 1
        controller, service, icon, _ = self._controller(setup_process)

        with patch("yt_music_telegram_sync.tray.subprocess.Popen") as popen:
            controller._finish_setup(setup_process)

        popen.assert_not_called()
        service.start.assert_called_once_with()
        icon.stop.assert_not_called()
        self.assertIsNone(controller._setup_process)

    def test_manual_restart_is_rejected_while_settings_are_open(self) -> None:
        setup_process = Mock()
        setup_process.poll.return_value = None
        controller, service, _, notify = self._controller(setup_process)

        with patch("yt_music_telegram_sync.tray.subprocess.Popen") as popen:
            controller._restart(Mock(), Mock())

        popen.assert_not_called()
        service.stop.assert_not_called()
        notify.assert_called_once()

    def test_notifications_can_be_disabled(self) -> None:
        controller = object.__new__(TrayController)
        controller._notifications_enabled = False
        controller.icon = Mock()

        controller._notify("Message", "Title")

        controller.icon.notify.assert_not_called()

    def test_tray_text_uses_configured_language(self) -> None:
        controller = object.__new__(TrayController)
        controller._language = "en"

        self.assertEqual(controller._t("tray.settings"), "Settings…")

    @unittest.skipUnless(os.name == "nt", "Windows notification flag")
    def test_notification_sound_can_be_disabled(self) -> None:
        icon = _NotificationIcon(
            "test",
            Image.new("RGBA", (16, 16)),
            "Title",
            sound_enabled=False,
        )

        with patch.object(icon, "_message") as message:
            icon._notify("Message", "Title")

        self.assertEqual(message.call_args.kwargs["dwInfoFlags"], 0x00000010)


if __name__ == "__main__":
    unittest.main()
