from __future__ import annotations

import base64
import logging
import re
import shutil
import tempfile
import threading
import time
import unicodedata
from collections import OrderedDict
from pathlib import Path
from typing import Any, Protocol

import httpx
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1
from mutagen.mp3 import MP3

from .models import Track

log = logging.getLogger(__name__)

_MAX_ARTWORK_BYTES = 8 * 1024 * 1024
_MAX_DOWNLOAD_SECONDS = 300.0
_SEARCH_RESULT_COUNT = 10
_FEATURE_CREDIT = re.compile(
    r"\s*[\[(]\s*(?:feat\.?|ft\.?|featuring)\s+[^)\]]+[\])]",
    flags=re.IGNORECASE,
)
_SILENCE_MP3_B64 = "SUQzBAAAAAAAIlRTU0UAAAAOAAADTGF2ZjYyLjMuMTAwAAAAAAAAAAAAAAD/+1AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABJbmZvAAAADwAAAAUAAAj5AEVFRUVFRUVFRUVFRUVFRUVFRUV0dHR0dHR0dHR0dHR0dHR0dHR0dKKioqKioqKioqKioqKioqKioqKi0dHR0dHR0dHR0dHR0dHR0dHR0dH//////////////////////////wAAAABMYXZjNjIuMTEAAAAAAAAAAAAAAAAkAwYAAAAAAAAI+ZbQn/gAAAAAAAAAAAAAAAAAAAAA//uQZAAP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAETEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVTEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUxBTUUzLjEwMFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVf/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVX/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAARVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVTEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQ=="


class TrackBackend(Protocol):
    def create(self, destination: Path, track: Track) -> bool: ...


class ArtworkLoader:
    def __init__(
        self,
        capacity: int = 16,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._capacity = capacity
        self._cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self._lock = threading.Lock()
        self._client = httpx.Client(
            timeout=httpx.Timeout(10.0),
            headers={"User-Agent": "YTMusicTelegramSync/1.0"},
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def get(self, url: str) -> tuple[bytes, str] | None:
        if not url:
            return None
        with self._lock:
            cached = self._cache.get(url)
            if cached is not None:
                self._cache.move_to_end(url)
                return cached

        try:
            with self._client.stream("GET", url) as response:
                response.raise_for_status()
                raw_length = response.headers.get("content-length")
                if raw_length is not None and int(raw_length) > _MAX_ARTWORK_BYTES:
                    log.warning(
                        "Обложка превышает лимит %d байт",
                        _MAX_ARTWORK_BYTES,
                    )
                    return None
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > _MAX_ARTWORK_BYTES:
                        log.warning(
                            "Обложка превышает лимит %d байт",
                            _MAX_ARTWORK_BYTES,
                        )
                        return None
                data = bytes(content)
                mime = response.headers.get("content-type", "image/jpeg").split(
                    ";", 1
                )[0]
        except (ValueError, httpx.HTTPError) as exc:
            log.warning("Не удалось скачать обложку: %s", exc)
            return None
        if not data:
            log.warning("Обложка пуста")
            return None
        if not mime.startswith("image/"):
            mime = "image/jpeg"
        value = (data, mime)
        with self._lock:
            self._cache[url] = value
            self._cache.move_to_end(url)
            while len(self._cache) > self._capacity:
                self._cache.popitem(last=False)
        return value


class PlaceholderBackend:
    def __init__(self, artwork: ArtworkLoader) -> None:
        self._artwork = artwork

    def create(self, destination: Path, track: Track) -> bool:
        destination.write_bytes(base64.b64decode(_SILENCE_MP3_B64))
        apply_track_tags(destination, track, self._artwork.get(track.cover_url))
        return True


class YtDlpBackend:
    def __init__(
        self,
        artwork: ArtworkLoader,
        *,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self._artwork = artwork
        self._cancel_event = cancel_event

    def create(self, destination: Path, track: Track) -> bool:
        if self._cancelled():
            return False
        try:
            from yt_dlp import YoutubeDL
            from yt_dlp.utils import DownloadError
        except ImportError:
            log.error("yt-dlp не установлен")
            return False

        query = f"ytsearch{_SEARCH_RESULT_COUNT}:{track.artist} {track.title}"
        deadline = time.monotonic() + _MAX_DOWNLOAD_SECONDS

        def check_cancelled(_status: object) -> None:
            if self._cancelled():
                raise _DownloadCancelled("download cancelled")
            if time.monotonic() >= deadline:
                raise _DownloadCancelled("download timed out")

        with tempfile.TemporaryDirectory(prefix="ytmts-download-") as temp_dir:
            output_template = str(Path(temp_dir) / "track.%(ext)s")
            options = {
                "format": "bestaudio/best",
                "outtmpl": output_template,
                "extract_flat": "in_playlist",
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "retries": 3,
                "socket_timeout": 20,
                "progress_hooks": [check_cancelled],
                "postprocessor_hooks": [check_cancelled],
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
            }
            try:
                with YoutubeDL(options) as downloader:
                    search = downloader.extract_info(query, download=False)
                    candidate = _select_search_result(search, track)
                    if candidate is None:
                        log.warning(
                            "Не найден подходящий результат YouTube для %s",
                            track.display_name,
                        )
                        return False
                    candidate_url = candidate.get("url")
                    if not isinstance(candidate_url, str) or not candidate_url:
                        log.warning(
                            "Результат поиска YouTube не содержит URL для %s",
                            track.display_name,
                        )
                        return False
                    log.info(
                        "Выбран результат YouTube для %s: %s (%s с)",
                        track.display_name,
                        candidate.get("title", candidate_url),
                        candidate.get("duration", "?"),
                    )
                    result = downloader.download([candidate_url])
            except (DownloadError, OSError, _DownloadCancelled) as exc:
                if self._cancelled():
                    log.info("Загрузка отменена: %s", track.display_name)
                else:
                    log.warning(
                        "Не удалось найти или скачать %s: %s",
                        track.display_name,
                        exc,
                    )
                return False
            downloaded = Path(temp_dir) / "track.mp3"
            if result != 0 or not downloaded.is_file():
                log.warning("yt-dlp не создал MP3 для %s", track.display_name)
                return False
            shutil.move(downloaded, destination)

        try:
            apply_track_tags(destination, track, self._artwork.get(track.cover_url))
        except Exception:
            log.exception("Не удалось записать метаданные в скачанный MP3")
        return True

    def _cancelled(self) -> bool:
        return self._cancel_event is not None and self._cancel_event.is_set()


class _DownloadCancelled(RuntimeError):
    pass


def _select_search_result(
    search: object,
    track: Track,
) -> dict[str, Any] | None:
    if not isinstance(search, dict):
        return None
    entries = search.get("entries")
    if not isinstance(entries, list):
        return None

    wanted_title = _search_words(_FEATURE_CREDIT.sub("", track.title))
    wanted_artist = _search_words(track.artist)
    if not wanted_title or not wanted_artist:
        return None

    matches: list[tuple[float, dict[str, Any]]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        candidate_title = _search_words(str(entry.get("title", "")))
        creator = " ".join(
            str(entry.get(field, ""))
            for field in ("artist", "channel", "uploader", "description")
        )
        candidate_artist = _search_words(creator)
        title_coverage = _word_coverage(wanted_title, candidate_title)
        artist_coverage = _word_coverage(
            wanted_artist,
            candidate_artist + candidate_title,
        )
        if title_coverage < 0.75 or artist_coverage < 0.5:
            continue

        normalized_title = " ".join(candidate_title)
        normalized_creator = " ".join(candidate_artist)
        wanted_title_phrase = " ".join(wanted_title)
        wanted_artist_phrase = " ".join(wanted_artist)
        score = title_coverage * 4 + artist_coverage * 3
        if wanted_title_phrase in normalized_title:
            score += 4
        if wanted_artist_phrase in f"{normalized_title} {normalized_creator}":
            score += 3
        if "topic" in candidate_artist:
            score += 0.5
        matches.append((score, entry))

    if not matches:
        return None
    return max(matches, key=lambda match: match[0])[1]


def _search_words(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    normalized = normalized.translate(str.maketrans("", "", "'’ʼ"))
    return tuple(re.findall(r"[^\W_]+", normalized, flags=re.UNICODE))


def _word_coverage(wanted: tuple[str, ...], candidate: tuple[str, ...]) -> float:
    return len(set(wanted) & set(candidate)) / len(set(wanted))


def apply_track_tags(
    path: Path, track: Track, artwork: tuple[bytes, str] | None
) -> None:
    audio = MP3(path, ID3=ID3)
    if audio.tags is None:
        audio.add_tags()
    assert audio.tags is not None
    for tag_name in ("TIT2", "TPE1", "TALB", "APIC"):
        audio.tags.delall(tag_name)
    audio.tags.add(TIT2(encoding=3, text=track.title[:500]))
    audio.tags.add(TPE1(encoding=3, text=track.artist[:500]))
    if track.album:
        audio.tags.add(TALB(encoding=3, text=track.album[:500]))
    if artwork is not None:
        data, mime = artwork
        audio.tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
    audio.save(v2_version=3)
