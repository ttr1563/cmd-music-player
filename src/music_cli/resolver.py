"""Short-lived extraction process: credentials only travel through stdin."""

from __future__ import annotations

import json
import sys
from http.cookiejar import Cookie
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

from yt_dlp import YoutubeDL
from yt_dlp.extractor.youtube import YoutubeIE as BaseYoutubeIE

from .provider import VIDEO_ID


def error_code(error: Exception) -> str:
    text = str(error).lower()
    if "sign in" in text or "login required" in text:
        return "login_required"
    if "429" in text or "rate-limit" in text:
        return "rate_limited"
    if "requested format" in text or "no video formats" in text:
        return "format_unavailable"
    return "extract_failed"


class QuietLogger:
    def debug(self, message: str) -> None:
        pass

    warning = debug
    error = debug


def account_extractor(headers: dict) -> BaseYoutubeIE:
    # yt-dlp has no public session-index option. Keep this narrow adapter pinned
    # and tested against the installed extractor, rather than selecting its default account.
    class YoutubeIE(BaseYoutubeIE):
        @staticmethod
        def _extract_session_index(*data):
            return int(headers.get("x-goog-authuser", "0"))

        def _extract_delegated_session_id(self, *args):
            return headers.get("x-goog-pageid") or None

    return YoutubeIE()


def resolve(payload: dict) -> dict:
    video_id = payload["id"]
    if not VIDEO_ID.fullmatch(video_id):
        raise ValueError("invalid video id")
    headers = payload.get("headers") or {}
    # Do not load user yt-dlp configuration, browser databases, or cookie files.
    with YoutubeDL(
        {
            "format": "bestaudio",
            "quiet": True,
            "no_warnings": True,
            "logger": QuietLogger(),
            "noplaylist": True,
            "cachedir": False,
            "socket_timeout": 15,
            "retries": 0,
            "extractor_retries": 0,
            "js_runtimes": {"deno": {}, "node": {}},
        }
    ) as ydl:
        if headers:
            ydl.add_info_extractor(account_extractor(headers))
        cookies: SimpleCookie = SimpleCookie()
        cookies.load(headers.get("cookie", ""))
        for name, morsel in cookies.items():
            ydl.cookiejar.set_cookie(
                Cookie(
                    version=0,
                    name=name,
                    value=morsel.value,
                    port=None,
                    port_specified=False,
                    domain=".youtube.com",
                    domain_specified=True,
                    domain_initial_dot=True,
                    path="/",
                    path_specified=True,
                    secure=True,
                    expires=None,
                    discard=True,
                    comment=None,
                    comment_url=None,
                    rest={},
                    rfc2109=False,
                )
            )
        authuser = int(headers.get("x-goog-authuser", "0"))
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}&authuser={authuser}",
            download=False,
        )
        url = info.get("url", "")
        host = urlsplit(url).hostname or ""
        if urlsplit(url).scheme != "https" or not (
            host.endswith(".googlevideo.com") or host.endswith(".youtube.com")
        ):
            raise ValueError("unexpected media URL")
        # Do not forward YouTube account cookies or Authorization to the CDN.
        return {"url": url}


def main() -> None:
    try:
        payload = json.loads(sys.stdin.buffer.read(128_000))
        result = resolve(payload)
        print(json.dumps(result))
    except Exception as error:
        # Extractor errors can include URLs/cookies. Never echo their raw text.
        print(json.dumps({"error": error_code(error)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
