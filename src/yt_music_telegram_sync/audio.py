from __future__ import annotations

import base64
import logging
import shutil
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Protocol

import httpx
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1
from mutagen.mp3 import MP3

from .models import Track

log = logging.getLogger(__name__)

_MAX_ARTWORK_BYTES = 8 * 1024 * 1024
_SILENCE_MP3_B64 = "SUQzBAAAAAAAIlRTU0UAAAAOAAADTGF2ZjYyLjMuMTAwAAAAAAAAAAAAAAD/+1AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABJbmZvAAAADwAAAAUAAAj5AEVFRUVFRUVFRUVFRUVFRUVFRUV0dHR0dHR0dHR0dHR0dHR0dHR0dKKioqKioqKioqKioqKioqKioqKi0dHR0dHR0dHR0dHR0dHR0dHR0dH//////////////////////////wAAAABMYXZjNjIuMTEAAAAAAAAAAAAAAAAkAwYAAAAAAAAI+ZbQn/gAAAAAAAAAAAAAAAAAAAAA//uQZAAP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAETEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVTEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVUxBTUUzLjEwMFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVf/7kmRAj/AAAGkAAAAIAAANIAAAAQAAAaQAAAAgAAA0gAAABFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVX/+5JkQI/wAABpAAAACAAADSAAAAEAAAGkAAAAIAAANIAAAARVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVTEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//uSZECP8AAAaQAAAAgAAA0gAAABAAABpAAAACAAADSAAAAEVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQ=="


class TrackBackend(Protocol):
    def create(self, destination: Path, track: Track) -> bool: ...


class ArtworkLoader:
    def __init__(self, capacity: int = 16) -> None:
        self._capacity = capacity
        self._cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self._lock = threading.Lock()
        self._client = httpx.Client(
            timeout=httpx.Timeout(10.0),
            headers={"User-Agent": "YTMusicTelegramSync/1.0"},
            follow_redirects=True,
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
            response = self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("Не удалось скачать обложку: %s", exc)
            return None
        data = response.content
        if not data or len(data) > _MAX_ARTWORK_BYTES:
            log.warning("Обложка пуста или превышает лимит %d байт", _MAX_ARTWORK_BYTES)
            return None
        mime = response.headers.get("content-type", "image/jpeg").split(";", 1)[0]
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
    def __init__(self, artwork: ArtworkLoader) -> None:
        self._artwork = artwork

    def create(self, destination: Path, track: Track) -> bool:
        try:
            from yt_dlp import YoutubeDL
            from yt_dlp.utils import DownloadError
        except ImportError:
            log.error("yt-dlp не установлен")
            return False

        query = f"ytsearch1:{track.artist} - {track.title} official audio"
        with tempfile.TemporaryDirectory(prefix="ytmts-download-") as temp_dir:
            output_template = str(Path(temp_dir) / "track.%(ext)s")
            options = {
                "format": "bestaudio/best",
                "outtmpl": output_template,
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "retries": 3,
                "socket_timeout": 20,
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
                    result = downloader.download([query])
            except (DownloadError, OSError) as exc:
                log.warning(
                    "Не удалось найти или скачать %s: %s", track.display_name, exc
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
