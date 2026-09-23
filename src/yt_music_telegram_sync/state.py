from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from .config import default_state_path
from .models import Track

log = logging.getLogger(__name__)
_STATE_VERSION = 3
_SUPPORTED_STATE_VERSIONS = {1, 2, 3}


@dataclass(frozen=True, slots=True)
class StoredTrack:
    track: Track
    message_id: int
    channel_message_id: int | None = None


@dataclass(frozen=True, slots=True)
class StoredEmojiStatus:
    kind: Literal["empty", "emoji", "collectible"]
    status_id: int = 0
    until: int | None = None


@dataclass(frozen=True, slots=True)
class TelegramRestoreState:
    playing_emoji_id: int = 0
    previous_emoji_status: StoredEmojiStatus | None = None
    playing_personal_channel_id: int = 0
    previous_personal_channel_id: int = 0


class StateStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_state_path()

    def load(self, destination: str = "profile_music") -> list[StoredTrack]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Не удалось прочитать состояние: %s", exc)
            return []
        if (
            not isinstance(payload, dict)
            or payload.get("version") not in _SUPPORTED_STATE_VERSIONS
        ):
            log.warning("Файл состояния имеет неизвестный формат")
            return []
        if payload.get("version") == 1:
            stored_destination = payload.get("destination", "profile_music")
            raw_entries = payload.get("tracks") if stored_destination == destination else []
        else:
            destinations = payload.get("destinations")
            raw_entries = (
                destinations.get(destination, [])
                if isinstance(destinations, dict)
                else []
            )
        if not isinstance(raw_entries, list):
            return []

        entries: list[StoredTrack] = []
        for raw_entry in raw_entries:
            try:
                if not isinstance(raw_entry, dict):
                    continue
                raw_track = raw_entry["track"]
                if not isinstance(raw_track, dict):
                    continue
                track = Track(
                    title=str(raw_track["title"]),
                    artist=str(raw_track["artist"]),
                    album=str(raw_track.get("album", "")),
                    cover_url=str(raw_track.get("cover_url", "")),
                    lastfm_url=str(raw_track.get("lastfm_url", "")),
                    mbid=str(raw_track.get("mbid", "")),
                )
                message_id = int(raw_entry["message_id"])
                raw_channel_message_id = raw_entry.get("channel_message_id")
                channel_message_id = (
                    int(raw_channel_message_id)
                    if raw_channel_message_id is not None
                    else None
                )
                if not track.title or not track.artist or message_id <= 0:
                    continue
                if channel_message_id is not None and channel_message_id <= 0:
                    channel_message_id = None
                entries.append(
                    StoredTrack(
                        track=track,
                        message_id=message_id,
                        channel_message_id=channel_message_id,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return entries

    def load_telegram_restore(self) -> TelegramRestoreState:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return TelegramRestoreState()
        if (
            not isinstance(payload, dict)
            or payload.get("version") not in _SUPPORTED_STATE_VERSIONS
        ):
            return TelegramRestoreState()
        raw_restore = payload.get("telegram_restore")
        if not isinstance(raw_restore, dict):
            return TelegramRestoreState()

        playing_emoji_id = _positive_int(raw_restore.get("playing_emoji_id"))
        previous_emoji_status = _load_emoji_status(
            raw_restore.get("previous_emoji_status")
        )
        if playing_emoji_id == 0 or previous_emoji_status is None:
            playing_emoji_id = 0
            previous_emoji_status = None

        playing_channel_id = _positive_int(
            raw_restore.get("playing_personal_channel_id")
        )
        previous_channel_id = _non_negative_int(
            raw_restore.get("previous_personal_channel_id")
        )
        if playing_channel_id == 0 or previous_channel_id is None:
            playing_channel_id = 0
            previous_channel_id = 0

        return TelegramRestoreState(
            playing_emoji_id=playing_emoji_id,
            previous_emoji_status=previous_emoji_status,
            playing_personal_channel_id=playing_channel_id,
            previous_personal_channel_id=previous_channel_id,
        )

    def save(
        self,
        entries: Iterable[StoredTrack],
        destination: str = "profile_music",
    ) -> None:
        existing = self._read_existing()
        destinations = _load_destinations(existing)
        destinations[destination] = [
            {
                "track": asdict(entry.track),
                "message_id": entry.message_id,
                "channel_message_id": entry.channel_message_id,
            }
            for entry in entries
        ]
        raw_restore: dict[str, object] | None = None
        if isinstance(existing, dict):
            existing_restore = existing.get("telegram_restore")
            if isinstance(existing_restore, dict):
                raw_restore = existing_restore
        self._write(destinations, raw_restore)

    def save_telegram_restore(self, state: TelegramRestoreState) -> None:
        existing = self._read_existing()
        destinations = _load_destinations(existing)
        previous_status = state.previous_emoji_status
        raw_restore: dict[str, object] = {
            "playing_emoji_id": state.playing_emoji_id,
            "previous_emoji_status": (
                asdict(previous_status) if previous_status is not None else None
            ),
            "playing_personal_channel_id": state.playing_personal_channel_id,
            "previous_personal_channel_id": state.previous_personal_channel_id,
        }
        self._write(destinations, raw_restore)

    def _read_existing(self) -> dict[str, object] | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _write(
        self,
        destinations: dict[str, object],
        telegram_restore: dict[str, object] | None,
    ) -> None:
        payload: dict[str, object] = {
            "version": _STATE_VERSION,
            "destinations": destinations,
        }
        if telegram_restore is not None:
            payload["telegram_restore"] = telegram_restore
        self.path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        descriptor, temp_name = tempfile.mkstemp(
            prefix="state-", suffix=".tmp", dir=self.path.parent
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.path)
        finally:
            temp_path.unlink(missing_ok=True)


def _load_destinations(existing: dict[str, object] | None) -> dict[str, object]:
    destinations: dict[str, object] = {}
    if not isinstance(existing, dict):
        return destinations
    existing_destinations = existing.get("destinations")
    if existing.get("version") in {2, 3} and isinstance(
        existing_destinations, dict
    ):
        destinations.update(existing_destinations)
    elif existing.get("version") == 1 and isinstance(existing.get("tracks"), list):
        legacy_destination = str(existing.get("destination", "profile_music"))
        destinations[legacy_destination] = existing["tracks"]
    return destinations


def _load_emoji_status(value: object) -> StoredEmojiStatus | None:
    if not isinstance(value, dict):
        return None
    kind = value.get("kind")
    if kind not in {"empty", "emoji", "collectible"}:
        return None
    status_id = _non_negative_int(value.get("status_id"))
    if status_id is None or (kind != "empty" and status_id == 0):
        return None
    raw_until = value.get("until")
    until = _non_negative_int(raw_until) if raw_until is not None else None
    if raw_until is not None and until is None:
        return None
    return StoredEmojiStatus(kind=kind, status_id=status_id, until=until)


def _positive_int(value: object) -> int:
    parsed = _non_negative_int(value)
    return parsed if parsed is not None and parsed > 0 else 0


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None
