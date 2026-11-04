"""Qt Designer setup dialog. Edit the layout in assets/setup_wizard.ui."""

from __future__ import annotations

import logging
import sys
import webbrowser
from pathlib import Path

from PySide6.QtCore import QEvent, QFile, QObject, QSignalBlocker, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QGroupBox,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QWidget,
)

from . import __version__
from .config import (
    AppConfig,
    ConfigurationError,
    default_config_path,
    default_draft_config_path,
    default_session_path,
    load_partial,
)
from .lastfm import LastFmClient, LastFmError
from .localization import LANGUAGE_LABELS, normalize_language, translate
from .setup_backend import (
    _run_async,
    _telegram_capture_personal_channel,
    _telegram_capture_playing_emoji,
    _telegram_is_authorized,
    _telegram_send_code,
    _telegram_sign_in,
)

ASSETS = Path(__file__).resolve().parent / "assets"
LASTFM_API_ACCOUNT_URL = "https://www.last.fm/api/account/create"
WEB_SCROBBLER_URL = "https://webscrobbler.com/"
log = logging.getLogger(__name__)


class SetupWizard(QObject):
    def __init__(self, config_path: Path | None = None) -> None:
        super().__init__()
        self._app = QApplication.instance() or QApplication(sys.argv)
        self.config_path = config_path or default_config_path()
        self.session_path = default_session_path()
        config = load_partial(
            self.config_path
            if self.config_path.is_file()
            else default_draft_config_path()
        )
        self.saved = False
        self._done = False
        self._phone_code_hash: str | None = None
        self._status_state = "info"

        ui_file = QFile(str(ASSETS / "setup_wizard.ui"))
        if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
            raise OSError(ui_file.errorString())
        loaded = QUiLoader().load(ui_file)
        ui_file.close()
        if not isinstance(loaded, QDialog):
            raise RuntimeError("Не удалось загрузить assets/setup_wizard.ui")
        self.root = loaded
        self.root.installEventFilter(self)
        self.root.resize(920, 840)
        self.root.setMinimumSize(800, 680)
        self._widget("versionLabel", QLabel).setText(f"v{__version__}")

        self.language_combo = self._widget("languageCombo", QComboBox)
        for code, label in LANGUAGE_LABELS.items():
            self.language_combo.addItem(label, code)
        self.language_combo.setCurrentIndex(
            self.language_combo.findData(normalize_language(config.ui_language))
        )
        self.dark_mode = self._widget("darkModeCheck", QCheckBox)
        self.dark_mode.setChecked(config.ui_theme != "light")
        self._set_text("lastfmUsernameEdit", config.lastfm_username)
        self._set_text("lastfmApiKeyEdit", config.lastfm_api_key)
        self._set_text("telegramApiIdEdit", str(config.telegram_api_id or ""))
        self._set_text("telegramApiHashEdit", config.telegram_api_hash)
        self._set_text("telegramPhoneEdit", config.telegram_phone)
        self._set_text("pollIntervalEdit", str(config.poll_interval_seconds))
        self._set_text("absentConfirmationsEdit", str(config.absent_confirmations))
        self._set_text("cacheSizeEdit", str(config.cache_size))
        self._set_text("downloadWorkersEdit", str(config.download_workers))
        self._set_text(
            "personalChannelEdit", str(config.telegram_personal_channel_id or "")
        )
        self._set_text("playingEmojiEdit", str(config.telegram_playing_emoji_id or ""))
        self._widget("emojiEnabledCheck", QCheckBox).setChecked(
            config.telegram_playing_emoji_enabled
        )
        self._widget("removeWhenIdleCheck", QCheckBox).setChecked(config.remove_when_idle)
        self._widget("notificationsEnabledCheck", QCheckBox).setChecked(
            config.notifications_enabled
        )
        self._widget("notificationSoundCheck", QCheckBox).setChecked(
            config.notification_sound_enabled
        )
        self.audio_mode = self._widget("audioModeCombo", QComboBox)
        for mode in ("placeholder", "mixed", "audio"):
            self.audio_mode.addItem(mode, mode)
        self.audio_mode.setCurrentIndex(self.audio_mode.findData(config.audio_mode))
        self.output_mode = self._widget("outputModeCombo", QComboBox)
        for mode in ("profile_music", "personal_channel", "profile_and_channel"):
            self.output_mode.addItem("", mode)
        self.output_mode.setCurrentIndex(
            self.output_mode.findData(config.telegram_output_mode)
        )

        self.language_combo.currentIndexChanged.connect(self._change_language)
        self.dark_mode.toggled.connect(self._apply_theme)
        self._widget("showLastfmSecretsCheck", QCheckBox).toggled.connect(
            self._toggle_secrets
        )
        self._widget("showTelegramSecretsCheck", QCheckBox).toggled.connect(
            self._toggle_secrets
        )
        self.output_mode.currentIndexChanged.connect(self._update_output_controls)
        self._widget("emojiEnabledCheck", QCheckBox).toggled.connect(
            self._update_emoji_controls
        )
        self._widget("notificationsEnabledCheck", QCheckBox).toggled.connect(
            self._update_notification_controls
        )
        for name, callback in (
            ("openApiButton", self._open_api_page),
            ("openScrobblerButton", self._open_scrobbler),
            ("testLastfmButton", self._test_lastfm),
            ("sendCodeButton", self._send_telegram_code),
            ("signInButton", self._sign_in_telegram),
            ("selectChannelButton", self._select_personal_channel),
            ("selectEmojiButton", self._select_playing_emoji),
            ("saveButton", self._save),
            ("cancelButton", self._cancel),
        ):
            self._widget(name, QPushButton).clicked.connect(callback)
        QShortcut(QKeySequence("Ctrl+S"), self.root).activated.connect(self._save)
        QShortcut(QKeySequence("Escape"), self.root).activated.connect(self._cancel)
        self._apply_language()
        self._apply_theme()
        self._update_output_controls()
        self._update_notification_controls()
        self._toggle_secrets(False)
        self._set_status(self._t("status.initial"))
        QTimer.singleShot(150, self._check_telegram_session)

    def _widget(self, name: str, cls: type[QWidget]):
        found = self.root.findChild(cls, name)
        if found is None:
            raise RuntimeError(f"В setup_wizard.ui не найден {name}")
        return found

    def _text(self, name: str) -> str:
        return self._widget(name, QLineEdit).text()

    def _set_text(self, name: str, value: str) -> None:
        self._widget(name, QLineEdit).setText(value)

    def _t(self, key: str, **values: object) -> str:
        return translate(key, self.language_combo.currentData(), **values)

    def run(self) -> bool:
        self.root.exec()
        return self.saved

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.root and event.type() == QEvent.Type.Close and not self._done:
            self._close()
        return False

    def _apply_language(self) -> None:
        self.root.setWindowTitle(self._t("window.title", version=__version__))
        labels = {
            "subtitleLabel": "header.subtitle",
            "languageLabel": "language.label",
            "lastfmUsernameLabel": "lastfm.username",
            "lastfmNote": "lastfm.note",
            "telegramPhoneLabel": "telegram.phone",
            "telegramCodeLabel": "telegram.code",
            "telegramPasswordLabel": "telegram.password",
            "telegramPasswordNote": "telegram.password_note",
            "pollIntervalLabel": "behavior.poll",
            "absentConfirmationsLabel": "behavior.absent",
            "cacheSizeLabel": "behavior.cache",
            "audioModeLabel": "behavior.audio_mode",
            "outputModeLabel": "behavior.output_mode",
            "personalChannelLabel": "behavior.channel",
            "downloadWorkersLabel": "behavior.workers",
            "notificationsNote": "notifications.note",
            "footerHint": "footer.hint",
        }
        for name, key in labels.items():
            self._widget(name, QLabel).setText(self._t(key))
        checks = {
            "darkModeCheck": "theme.dark",
            "showLastfmSecretsCheck": "credentials.show",
            "showTelegramSecretsCheck": "credentials.show",
            "emojiEnabledCheck": "behavior.emoji",
            "removeWhenIdleCheck": "behavior.remove_idle",
            "notificationsEnabledCheck": "notifications.enabled",
            "notificationSoundCheck": "notifications.sound",
        }
        for name, key in checks.items():
            self._widget(name, QCheckBox).setText(self._t(key))
        buttons = {
            "openApiButton": "lastfm.get_api_key",
            "testLastfmButton": "lastfm.test",
            "sendCodeButton": "telegram.send_code",
            "signInButton": "telegram.sign_in",
            "selectChannelButton": "behavior.select",
            "selectEmojiButton": "behavior.select",
            "saveButton": "footer.save",
            "cancelButton": "footer.cancel",
        }
        for name, key in buttons.items():
            self._widget(name, QPushButton).setText(self._t(key))
        self._widget("behaviorGroup", QGroupBox).setTitle(self._t("behavior.title"))
        self._widget("notificationsGroup", QGroupBox).setTitle(
            self._t("notifications.title")
        )
        self._widget("tabs", QTabWidget).setTabText(2, self._t("tabs.sync").strip())
        for index, key in enumerate(
            ("behavior.output_profile", "behavior.output_channel", "behavior.output_both")
        ):
            self.output_mode.setItemText(index, self._t(key))

    def _change_language(self) -> None:
        self._apply_language()
        self._set_status(self._t("status.language_changed"))

    def _apply_theme(self) -> None:
        filename = "setup_wizard.qss" if self.dark_mode.isChecked() else "setup_wizard_light.qss"
        self.root.setStyleSheet((ASSETS / filename).read_text(encoding="utf-8"))

    def _toggle_secrets(self, show: bool) -> None:
        for name in ("showLastfmSecretsCheck", "showTelegramSecretsCheck"):
            checkbox = self._widget(name, QCheckBox)
            with QSignalBlocker(checkbox):
                checkbox.setChecked(show)
        mode = QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
        for name in ("lastfmApiKeyEdit", "telegramApiHashEdit", "telegramPhoneEdit"):
            self._widget(name, QLineEdit).setEchoMode(mode)

    def _update_output_controls(self) -> None:
        mode = self.output_mode.currentData()
        channel = mode in {"personal_channel", "profile_and_channel"}
        profile = mode in {"profile_music", "profile_and_channel"}
        self._widget("personalChannelEdit", QLineEdit).setEnabled(channel)
        self._widget("selectChannelButton", QPushButton).setEnabled(channel)
        self._widget("removeWhenIdleCheck", QCheckBox).setEnabled(profile)
        self._update_emoji_controls()

    def _update_emoji_controls(self) -> None:
        enabled = self._widget("emojiEnabledCheck", QCheckBox).isChecked()
        self._widget("playingEmojiEdit", QLineEdit).setEnabled(enabled)
        self._widget("selectEmojiButton", QPushButton).setEnabled(enabled)

    def _update_notification_controls(self) -> None:
        enabled = self._widget("notificationsEnabledCheck", QCheckBox).isChecked()
        self._widget("notificationSoundCheck", QCheckBox).setEnabled(enabled)

    def _set_status(self, message: str, state: str = "info") -> None:
        self._widget("statusLabel", QLabel).setText(message)
        self._status_state = state
        colors = {
            "info": "#61b3e5",
            "pending": "#e3b341",
            "success": "#68d391",
            "warning": "#e3b341",
            "error": "#f85149",
        }
        self._widget("statusIndicator", QLabel).setStyleSheet(
            f"color: {colors.get(state, colors['info'])};"
        )

    def _config_from_form(self) -> AppConfig:
        try:
            config = AppConfig(
                lastfm_username=self._text("lastfmUsernameEdit").strip(),
                lastfm_api_key=self._text("lastfmApiKeyEdit").strip(),
                telegram_api_id=int(self._text("telegramApiIdEdit").strip()),
                telegram_api_hash=self._text("telegramApiHashEdit").strip(),
                telegram_phone=self._text("telegramPhoneEdit").strip(),
                poll_interval_seconds=float(self._text("pollIntervalEdit").strip()),
                absent_confirmations=int(self._text("absentConfirmationsEdit").strip()),
                cache_size=int(self._text("cacheSizeEdit").strip()),
                audio_mode=self.audio_mode.currentData(),
                download_workers=int(self._text("downloadWorkersEdit").strip()),
                remove_when_idle=self._widget("removeWhenIdleCheck", QCheckBox).isChecked(),
                telegram_output_mode=self.output_mode.currentData(),
                telegram_personal_channel_id=int(self._text("personalChannelEdit").strip() or "0"),
                telegram_playing_emoji_enabled=self._widget(
                    "emojiEnabledCheck", QCheckBox
                ).isChecked(),
                telegram_playing_emoji_id=int(self._text("playingEmojiEdit").strip() or "0"),
                notifications_enabled=self._widget(
                    "notificationsEnabledCheck", QCheckBox
                ).isChecked(),
                notification_sound_enabled=self._widget(
                    "notificationSoundCheck", QCheckBox
                ).isChecked(),
                ui_language=self.language_combo.currentData(),
                ui_theme="dark" if self.dark_mode.isChecked() else "light",
            )
        except ValueError as exc:
            raise ConfigurationError(self._t("setup.numeric_invalid")) from exc
        config.validate()
        return config

    def _telegram_api_credentials(self) -> tuple[int, str]:
        try:
            api_id = int(self._text("telegramApiIdEdit").strip())
        except ValueError as exc:
            raise ConfigurationError(self._t("setup.api_id_number")) from exc
        api_hash = self._text("telegramApiHashEdit").strip()
        if not api_id or not api_hash:
            raise ConfigurationError(self._t("setup.api_credentials_required"))
        return api_id, api_hash

    def _telegram_credentials(self) -> tuple[int, str, str]:
        api_id, api_hash = self._telegram_api_credentials()
        phone = self._text("telegramPhoneEdit").strip()
        if not phone:
            raise ConfigurationError(self._t("setup.phone_required"))
        return api_id, api_hash, phone

    def _show_error(self, title: str, error: Exception | str) -> None:
        QMessageBox.critical(self.root, title, str(error))

    def _test_lastfm(self) -> None:
        username = self._text("lastfmUsernameEdit").strip()
        api_key = self._text("lastfmApiKeyEdit").strip()
        if not username or not api_key:
            self._show_error("Last.fm", self._t("lastfm.credentials_required"))
            return
        self._set_status(self._t("lastfm.checking"), "pending")
        self._app.processEvents()
        try:
            with LastFmClient(api_key, username, language=self.language_combo.currentData()) as client:
                user = client.get_user()
                track = client.get_now_playing()
        except LastFmError as exc:
            self._set_status(self._t("lastfm.error", error=exc), "error")
            self._show_error("Last.fm", exc)
            return
        self._set_text("lastfmUsernameEdit", user.username)
        result = (
            self._t("lastfm.connected_idle", username=user.username)
            if track is None
            else self._t(
                "lastfm.connected_track", username=user.username, track=track.display_name
            )
        )
        self._set_status(result, "success")
        QMessageBox.information(self.root, "Last.fm", result)
        self._save_draft()

    def _check_telegram_session(self) -> None:
        try:
            api_id, api_hash = self._telegram_api_credentials()
            authorized = _run_async(
                _telegram_is_authorized(self.session_path, api_id, api_hash)
            )
        except Exception:  # noqa: BLE001 - optional startup probe
            return
        if authorized:
            self._set_status(self._t("telegram.session_authorized"), "success")

    def _send_telegram_code(self) -> None:
        try:
            api_id, api_hash, phone = self._telegram_credentials()
            self._save_draft()
            self.session_path.parent.mkdir(parents=True, exist_ok=True)
            self._set_status(self._t("telegram.sending_code"), "pending")
            self._app.processEvents()
            result = _run_async(
                _telegram_send_code(self.session_path, api_id, api_hash, phone)
            )
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports Telegram errors
            self._show_error("Telegram", exc)
            self._set_status(self._t("telegram.error", error=exc), "error")
            return
        if result is None:
            self._set_status(self._t("telegram.already_authorized"), "success")
        else:
            self._phone_code_hash = result
            self._set_status(self._t("telegram.code_sent"), "success")

    def _sign_in_telegram(self) -> None:
        try:
            api_id, api_hash, phone = self._telegram_credentials()
            code = self._text("telegramCodeEdit").strip().replace(" ", "")
            if not code:
                raise ConfigurationError(self._t("telegram.code_required"))
            self._set_status(self._t("telegram.authorizing"), "pending")
            self._app.processEvents()
            needs_password = _run_async(
                _telegram_sign_in(
                    self.session_path,
                    api_id,
                    api_hash,
                    phone,
                    code,
                    self._phone_code_hash,
                    self._text("telegramPasswordEdit"),
                    self._prompt_telegram_password,
                )
            )
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports Telegram errors
            self._show_error("Telegram", exc)
            self._set_status(self._t("telegram.error", error=exc), "error")
            return
        if needs_password:
            self._set_status(self._t("telegram.2fa_cancelled"), "warning")
            QMessageBox.warning(self.root, "Telegram 2FA", self._t("telegram.2fa_retry"))
        else:
            self._set_text("telegramPasswordEdit", "")
            self._set_status(self._t("telegram.authorized"), "success")

    def _prompt_telegram_password(self) -> str | None:
        password, ok = QInputDialog.getText(
            self.root,
            "Telegram 2FA",
            self._t("telegram.2fa_prompt"),
            QLineEdit.EchoMode.Password,
        )
        return password if ok else None

    def _select_playing_emoji(self) -> None:
        try:
            api_id, api_hash = self._telegram_api_credentials()
            self._set_status(self._t("emoji.selecting"), "pending")
            self._app.processEvents()
            document_id = _run_async(
                _telegram_capture_playing_emoji(
                    self.session_path,
                    api_id,
                    api_hash,
                    self._prompt_playing_emoji_selection,
                    language=self.language_combo.currentData(),
                )
            )
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports Telegram errors
            self._show_error("Telegram emoji status", exc)
            self._set_status(self._t("emoji.error", error=exc), "error")
            return
        if document_id is None:
            self._set_status(self._t("emoji.cancelled"), "warning")
            return
        self._set_text("playingEmojiEdit", str(document_id))
        self._set_status(self._t("emoji.selected"), "success")
        self._save_draft()

    def _prompt_playing_emoji_selection(self) -> bool:
        return QMessageBox.question(
            self.root, self._t("emoji.dialog_title"), self._t("emoji.dialog")
        ) == QMessageBox.StandardButton.Yes

    def _select_personal_channel(self) -> None:
        try:
            api_id, api_hash = self._telegram_api_credentials()
            self._set_status(self._t("channel.selecting"), "pending")
            self._app.processEvents()
            selected = _run_async(
                _telegram_capture_personal_channel(
                    self.session_path,
                    api_id,
                    api_hash,
                    self._prompt_personal_channel_selection,
                    language=self.language_combo.currentData(),
                )
            )
        except Exception as exc:  # noqa: BLE001 - GUI boundary reports Telegram errors
            self._show_error(self._t("channel.dialog_title"), exc)
            self._set_status(self._t("channel.error", error=exc), "error")
            return
        if selected is None:
            self._set_status(self._t("channel.cancelled"), "warning")
            return
        channel_id, title = selected
        self._set_text("personalChannelEdit", str(channel_id))
        self._set_status(self._t("channel.selected", title=title), "success")
        self._save_draft()

    def _prompt_personal_channel_selection(self) -> bool:
        return QMessageBox.question(
            self.root, self._t("channel.dialog_title"), self._t("channel.dialog")
        ) == QMessageBox.StandardButton.Yes

    def _save(self) -> None:
        self._set_status(self._t("setup.saving"), "pending")
        if self._persist_config(show_errors=True):
            self.saved = True
            self._done = True
            self.root.removeEventFilter(self)
            self.root.accept()

    def _persist_config(self, *, show_errors: bool) -> bool:
        try:
            config = self._config_from_form()
            config.save(self.config_path)
            default_draft_config_path().unlink(missing_ok=True)
        except (ConfigurationError, OSError) as exc:
            if show_errors:
                self._show_error(self._t("setup.title"), exc)
                self._set_status(self._t("setup.save_error", error=exc), "error")
            return False
        log.info(
            "Настройки сохранены: audio_mode=%s, output_mode=%s, ui_language=%s, ui_theme=%s",
            config.audio_mode,
            config.telegram_output_mode,
            config.ui_language,
            config.ui_theme,
        )
        return True

    def _save_draft(self) -> None:
        try:
            self._config_from_form().save(default_draft_config_path())
        except (ConfigurationError, OSError):
            return

    def _open_api_page(self) -> None:
        webbrowser.open(LASTFM_API_ACCOUNT_URL)

    def _open_scrobbler(self) -> None:
        webbrowser.open(WEB_SCROBBLER_URL)

    def _close(self) -> None:
        self.saved = self._persist_config(show_errors=False)
        if not self.saved:
            self._save_draft()
        self._done = True
        self.root.removeEventFilter(self)

    def _cancel(self) -> None:
        self._done = True
        self.root.removeEventFilter(self)
        self.root.reject()


def run_setup(config_path: Path | None = None) -> bool:
    return SetupWizard(config_path).run()
