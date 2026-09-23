from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from .localization import SUPPORTED_LANGUAGES, translate

APP_NAME = "YTMusicTelegramSync"


class ConfigurationError(ValueError):
    pass


def app_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def default_config_path() -> Path:
    return app_data_dir() / "config.json"


def default_draft_config_path() -> Path:
    return app_data_dir() / "config.draft.json"


def default_session_path() -> Path:
    return app_data_dir() / "telegram"


def default_log_path() -> Path:
    return app_data_dir() / "logs" / "app.log"


def default_state_path() -> Path:
    return app_data_dir() / "state.json"


@dataclass(slots=True)
class AppConfig:
    lastfm_username: str = ""
    lastfm_api_key: str = ""
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_phone: str = ""
    poll_interval_seconds: float = 5.0
    absent_confirmations: int = 3
    cache_size: int = 20
    audio_mode: str = "placeholder"
    download_workers: int = 2
    remove_when_idle: bool = True
    telegram_output_mode: str = "profile_music"
    telegram_personal_channel_id: int = 0
    telegram_playing_emoji_enabled: bool = False
    telegram_playing_emoji_id: int = 0
    notifications_enabled: bool = True
    notification_sound_enabled: bool = True
    ui_language: str = "ru"
    ui_theme: str = "dark"

    def validate(self) -> None:
        language = self.ui_language if self.ui_language in SUPPORTED_LANGUAGES else "ru"
        if self.ui_language not in SUPPORTED_LANGUAGES:
            raise ConfigurationError(translate("config.language", language))
        if self.ui_theme not in {"dark", "light"}:
            raise ConfigurationError(translate("config.theme", language))
        missing: list[str] = []
        if not self.lastfm_username.strip():
            missing.append("Last.fm username")
        if not self.lastfm_api_key.strip():
            missing.append("Last.fm API key")
        if self.telegram_api_id <= 0:
            missing.append("Telegram API ID")
        if not self.telegram_api_hash.strip():
            missing.append("Telegram API hash")
        if missing:
            raise ConfigurationError(
                translate("config.missing", language, fields=", ".join(missing))
            )
        if self.poll_interval_seconds < 3:
            raise ConfigurationError(translate("config.poll_min", language))
        if not 1 <= self.absent_confirmations <= 20:
            raise ConfigurationError(translate("config.absent_range", language))
        if not 1 <= self.cache_size <= 100:
            raise ConfigurationError(translate("config.cache_range", language))
        if self.audio_mode not in {"placeholder", "mixed", "audio"}:
            raise ConfigurationError(translate("config.audio_mode", language))
        if not 1 <= self.download_workers <= 4:
            raise ConfigurationError(translate("config.workers_range", language))
        if self.telegram_output_mode not in {
            "profile_music",
            "personal_channel",
            "profile_and_channel",
        }:
            raise ConfigurationError(translate("config.output_mode", language))
        if not 0 <= self.telegram_personal_channel_id <= (1 << 63) - 1:
            raise ConfigurationError(translate("config.channel_id", language))
        if (
            self.telegram_output_mode in {"personal_channel", "profile_and_channel"}
            and self.telegram_personal_channel_id == 0
        ):
            raise ConfigurationError(translate("config.channel_required", language))
        if not 0 <= self.telegram_playing_emoji_id <= (1 << 63) - 1:
            raise ConfigurationError(translate("config.emoji_id", language))
        if self.telegram_playing_emoji_enabled and self.telegram_playing_emoji_id == 0:
            raise ConfigurationError(translate("config.emoji_required", language))

    @classmethod
    def load(cls, path: Path | None = None) -> AppConfig:
        config_path = path or default_config_path()
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigurationError(
                translate("config.not_created", "ru")
            ) from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(
                translate("config.read_failed", "ru", error=exc)
            ) from exc

        if not isinstance(raw, dict):
            raise ConfigurationError(
                translate(
                    "config.invalid",
                    "ru",
                    error="корневое значение JSON должно быть объектом",
                )
            )

        allowed = {field.name for field in fields(cls)}
        values = {key: value for key, value in raw.items() if key in allowed}
        _migrate_emoji_enabled(raw, values)
        try:
            config = cls(**values)
            config.validate()
        except ConfigurationError:
            raise
        except (AttributeError, TypeError) as exc:
            language = str(raw.get("ui_language", "ru"))
            raise ConfigurationError(
                translate("config.invalid", language, error=exc)
            ) from exc
        return config

    def save(self, path: Path | None = None) -> None:
        self.validate()
        config_path = path or default_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n"

        handle, temp_name = tempfile.mkstemp(
            prefix="config-", suffix=".tmp", dir=config_path.parent
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, config_path)
        finally:
            temp_path.unlink(missing_ok=True)


def load_partial(path: Path | None = None) -> AppConfig:
    config_path = path or default_config_path()
    try:
        raw: Any = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return AppConfig()
    if not isinstance(raw, dict):
        return AppConfig()
    allowed = {field.name for field in fields(AppConfig)}
    values = {key: value for key, value in raw.items() if key in allowed}
    _migrate_emoji_enabled(raw, values)
    try:
        return AppConfig(**values)
    except TypeError:
        return AppConfig()


def _migrate_emoji_enabled(raw: dict[str, Any], values: dict[str, Any]) -> None:
    if "telegram_playing_emoji_enabled" not in raw:
        values["telegram_playing_emoji_enabled"] = bool(
            raw.get("telegram_playing_emoji_id", 0)
        )
