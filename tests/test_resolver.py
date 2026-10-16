from unittest.mock import Mock

import pytest
from yt_dlp import YoutubeDL

from music_cli.resolver import account_extractor, error_code, resolve


def test_selected_account_overrides_extractor_default():
    extractor = account_extractor({"x-goog-authuser": "2", "x-goog-pageid": "selected-brand"})
    with YoutubeDL({"quiet": True, "cachedir": False}) as ydl:
        ydl.add_info_extractor(extractor)
        assert ydl.get_info_extractor("Youtube") is extractor
        headers = extractor._generate_cookie_auth_headers(
            ytcfg={"SESSION_INDEX": 0, "DELEGATED_SESSION_ID": "wrong-brand"},
        )
    assert headers["X-Goog-AuthUser"] == 2
    assert headers["X-Goog-PageId"] == "selected-brand"


def test_primary_account_does_not_inherit_default_brand():
    extractor = account_extractor({"x-goog-authuser": "1"})
    with YoutubeDL({"quiet": True, "cachedir": False}) as ydl:
        ydl.add_info_extractor(extractor)
        headers = extractor._generate_cookie_auth_headers(
            ytcfg={"SESSION_INDEX": 0, "DELEGATED_SESSION_ID": "wrong-brand"},
        )
    assert headers["X-Goog-AuthUser"] == 1
    assert "X-Goog-PageId" not in headers


def test_resolver_cookies_stay_in_memory_and_not_in_cdn_output(monkeypatch):
    engine = Mock()
    engine.extract_info.return_value = {
        "url": "https://r1.googlevideo.com/videoplayback?signed-token",
        "http_headers": {"Cookie": "sensitive"},
    }
    context = Mock()
    context.__enter__ = Mock(return_value=engine)
    context.__exit__ = Mock(return_value=False)
    factory = Mock(return_value=context)
    monkeypatch.setattr("music_cli.resolver.YoutubeDL", factory)
    result = resolve(
        {
            "id": "abcdefghijk",
            "headers": {
                "cookie": "SID=private-cookie",
                "x-goog-authuser": "2",
            },
        }
    )
    options = factory.call_args.args[0]
    assert options["cachedir"] is False
    assert options["format"] == "bestaudio"
    assert "cookiefile" not in options and "cookiesfrombrowser" not in options
    assert "Cookie" not in result and "private-cookie" not in str(result)
    assert engine.cookiejar.set_cookie.call_args.args[0].value == "private-cookie"
    assert "authuser=2" in engine.extract_info.call_args.args[0]
    assert engine.extract_info.call_args.args[0].startswith("https://music.youtube.com/watch?")


def test_invalid_id_rejected_before_extractor(monkeypatch):
    factory = Mock()
    monkeypatch.setattr("music_cli.resolver.YoutubeDL", factory)
    with pytest.raises(ValueError):
        resolve({"id": "--bad-option"})
    factory.assert_not_called()


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("Sign in to confirm you're not a bot; Cookie=secret", "login_required"),
        ("HTTP Error 429 sensitive", "rate_limited"),
        ("Requested format is not available https://private", "format_unavailable"),
        ("Cookie=secret", "extract_failed"),
    ],
)
def test_extractor_errors_are_mapped_without_exposing_details(message, code):
    assert error_code(RuntimeError(message)) == code
