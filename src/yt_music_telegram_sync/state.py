from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import default_state_path
from .models import Track

log = logging.getLogger(__name__)
_STATE_VERSION = 1


@dataclass(frozen=True, slots=True)
class StoredTrack:
    track: Track
    message_id: int


class StateStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_state_path()

    def load(self) -> list[StoredTrack]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Не удалось прочитать состояние: %s", exc)
            return []
        if not isinstance(payload, dict) or payload.get("version") != _STATE_VERSION:
            log.warning("Файл состояния имеет неизвестный формат")
            return []
        raw_entries = payload.get("tracks")
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
                if not track.title or not track.artist or message_id <= 0:
                    continue
                entries.append(StoredTrack(track=track, message_id=message_id))
            except (KeyError, TypeError, ValueError):
                continue
        return entries

    def save(self, entries: Iterable[StoredTrack]) -> None:
        payload = {
            "version": _STATE_VERSION,
            "tracks": [
                {"track": asdict(entry.track), "message_id": entry.message_id}
                for entry in entries
            ],
        }
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
