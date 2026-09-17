from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return _WHITESPACE_RE.sub(" ", normalized)


@dataclass(frozen=True, slots=True)
class Track:
    title: str
    artist: str
    album: str = ""
    cover_url: str = ""
    lastfm_url: str = ""
    mbid: str = ""

    @property
    def identity(self) -> tuple[str, ...]:
        if self.mbid:
            return ("mbid", self.mbid.casefold())
        return (
            "metadata",
            _normalize(self.artist),
            _normalize(self.title),
            _normalize(self.album),
        )

    @property
    def display_name(self) -> str:
        return f"{self.artist} — {self.title}"
