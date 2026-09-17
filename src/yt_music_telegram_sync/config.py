from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

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

    def validate(self) -> None:
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
            raise ConfigurationError("Не заполнено: " + ", ".join(missing))
        if self.poll_interval_seconds < 3:
            raise ConfigurationError("Интервал Last.fm не может быть меньше 3 секунд")
        if not 1 <= self.absent_confirmations <= 20:
            raise ConfigurationError("Подтверждений отсутствия должно быть от 1 до 20")
        if not 1 <= self.cache_size <= 100:
            raise ConfigurationError("Размер кэша должен быть от 1 до 100")
        if self.audio_mode not in {"placeholder", "mixed", "audio"}:
            raise ConfigurationError("Неизвестный режим аудио")
        if not 1 <= self.download_workers <= 4:
            raise ConfigurationError("Количество загрузчиков должно быть от 1 до 4")

    @classmethod
    def load(cls, path: Path | None = None) -> AppConfig:
        config_path = path or default_config_path()
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigurationError("Конфигурация ещё не создана") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(
                f"Не удалось прочитать конфигурацию: {exc}"
            ) from exc

        allowed = {field.name for field in fields(cls)}
        values = {key: value for key, value in raw.items() if key in allowed}
        try:
            config = cls(**values)
        except TypeError as exc:
            raise ConfigurationError(f"Некорректная конфигурация: {exc}") from exc
        config.validate()
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
        raw: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return AppConfig()
    allowed = {field.name for field in fields(AppConfig)}
    values = {key: value for key, value in raw.items() if key in allowed}
    try:
        return AppConfig(**values)
    except TypeError:
        return AppConfig()
