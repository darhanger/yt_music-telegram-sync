from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Self

import httpx

from .localization import translate
from .models import Track

API_URL = "https://ws.audioscrobbler.com/2.0/"
USER_AGENT = "YTMusicTelegramSync/1.0 (+https://github.com/)"


class LastFmError(RuntimeError):
    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code

    @property
    def is_transient(self) -> bool:
        return self.code in {11, 16, 29} or self.code is None


@dataclass(frozen=True, slots=True)
class LastFmUser:
    username: str
    real_name: str


class LastFmClient:
    def __init__(
        self,
        api_key: str,
        username: str,
        *,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        language: str = "ru",
    ) -> None:
        self.api_key = api_key
        self.username = username
        self._language = language
        self._client = httpx.Client(
            base_url=API_URL,
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get_user(self) -> LastFmUser:
        payload = self._request("user.getInfo", user=self.username)
        user = payload.get("user")
        if not isinstance(user, dict):
            raise LastFmError(translate("lastfm.no_user", self._language))
        username = _text(user.get("name"))
        if not username:
            raise LastFmError(translate("lastfm.empty_user", self._language))
        return LastFmUser(username=username, real_name=_text(user.get("realname")))

    def get_now_playing(self) -> Track | None:
        payload = self._request(
            "user.getRecentTracks", user=self.username, limit="1", extended="0"
        )
        recent = payload.get("recenttracks")
        if not isinstance(recent, dict):
            return None
        raw_tracks = recent.get("track")
        if isinstance(raw_tracks, dict):
            raw_track: dict[str, Any] | None = raw_tracks
        elif isinstance(raw_tracks, list) and raw_tracks:
            first = raw_tracks[0]
            raw_track = first if isinstance(first, dict) else None
        else:
            raw_track = None

        if raw_track is None or not _is_now_playing(raw_track):
            return None
        return _parse_track(raw_track, language=self._language)

    def _request(self, method: str, **params: str) -> dict[str, Any]:
        query = {
            "method": method,
            "api_key": self.api_key,
            "format": "json",
            **params,
        }
        try:
            response = self._client.get("", params=query)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise LastFmError(
                translate(
                    "lastfm.http_error",
                    self._language,
                    status=exc.response.status_code,
                )
            ) from exc
        except httpx.RequestError as exc:
            raise LastFmError(
                translate(
                    "lastfm.network_error",
                    self._language,
                    error_type=type(exc).__name__,
                )
            ) from exc
        except ValueError as exc:
            raise LastFmError(
                translate("lastfm.invalid_json", self._language)
            ) from exc
        if not isinstance(payload, dict):
            raise LastFmError(
                translate("lastfm.unexpected_response", self._language)
            )
        if "error" in payload:
            try:
                code = int(payload["error"])
            except (TypeError, ValueError):
                code = None
            message = _text(payload.get("message")) or translate(
                "lastfm.unknown_error",
                self._language,
            )
            raise LastFmError(message, code)
        return payload


def _is_now_playing(raw_track: dict[str, Any]) -> bool:
    attributes = raw_track.get("@attr")
    if not isinstance(attributes, dict):
        return False
    value = attributes.get("nowplaying")
    return str(value).casefold() == "true"


def _parse_track(raw_track: dict[str, Any], *, language: str = "ru") -> Track:
    title = _text(raw_track.get("name"))
    artist = _nested_text(raw_track.get("artist"))
    if not title or not artist:
        raise LastFmError(translate("lastfm.track_metadata_missing", language))

    images = raw_track.get("image")
    cover_url = ""
    if isinstance(images, list):
        for image in reversed(images):
            candidate = _nested_text(image)
            if candidate:
                cover_url = candidate
                break

    return Track(
        title=title,
        artist=artist,
        album=_nested_text(raw_track.get("album")),
        cover_url=cover_url,
        lastfm_url=_text(raw_track.get("url")),
        mbid=_text(raw_track.get("mbid")),
    )


def _nested_text(value: Any) -> str:
    if isinstance(value, dict):
        return _text(value.get("#text"))
    return _text(value)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
