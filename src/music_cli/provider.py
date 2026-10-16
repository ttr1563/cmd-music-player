"""Service operations are separate from terminal and playback code."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import partial
from typing import Any

import requests
from ytmusicapi import YTMusic, setup

from .storage import UserError

VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")


@dataclass(frozen=True)
class Item:
    id: str
    title: str
    subtitle: str = ""
    kind: str = "song"


def login_headers(cookie: str, authorization: str, authuser: str, pageid: str = "") -> dict:
    values = (cookie, authorization, authuser, pageid)
    if any("\r" in value or "\n" in value for value in values):
        raise UserError("各入力欄にはheaderの値だけを1行で入力してください。")
    if not authuser.isdecimal() or not cookie or "SAPISIDHASH" not in authorization:
        raise UserError("Cookie・Authorization・X-Goog-Authuserを同じrequestから入力してください。")
    import json

    raw = f"cookie: {cookie}\nauthorization: {authorization}\nx-goog-authuser: {authuser}"
    if pageid:
        raw += f"\nx-goog-pageid: {pageid}"
    return json.loads(setup(headers_raw=raw))


class YouTubeMusic:
    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = headers

    def _call(self, method: str, **kwargs: Any) -> Any:
        try:
            with requests.Session() as session:
                session.request = partial(session.request, timeout=15)
                api = YTMusic(
                    auth=self.headers.copy() if self.headers else None, requests_session=session
                )
                return getattr(api, method)(**kwargs)
        except Exception as error:
            raise UserError(
                "YouTube Musicへ接続できません。接続を確認し、"
                "ログイン中ならmusic loginで認証を更新してください。"
            ) from error

    def account_info(self) -> dict:
        return self._call("get_account_info")

    @staticmethod
    def _songs(rows: list[dict]) -> list[Item]:
        return [
            Item(
                row["videoId"],
                row.get("title", "不明な曲"),
                " / ".join(a.get("name", "") for a in row.get("artists", [])),
            )
            for row in rows
            if VIDEO_ID.fullmatch(row.get("videoId") or "") and row.get("isAvailable", True)
        ]

    def search(self, query: str) -> list[Item]:
        return self._songs(self._call("search", query=query, filter="songs", limit=30))[:30]

    def library(self) -> list[Item]:
        self._require_login()
        return self._songs(self._call("get_library_songs", limit=100))[:100]

    def playlists(self) -> list[Item]:
        self._require_login()
        rows = self._call("get_library_playlists", limit=100)
        return [
            Item(row["playlistId"], row.get("title", "プレイリスト"), kind="playlist")
            for row in rows
            if row.get("playlistId")
        ][:100]

    def playlist(self, playlist_id: str) -> list[Item]:
        return self._songs(self._call("get_playlist", playlistId=playlist_id, limit=100)["tracks"])[
            :100
        ]

    def _require_login(self) -> None:
        if not self.headers:
            raise UserError(
                "この機能にはログインが必要です。終了後にmusic login 名前を実行してください。"
            )
