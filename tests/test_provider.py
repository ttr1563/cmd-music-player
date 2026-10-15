from unittest.mock import Mock

import pytest
from ytmusicapi import YTMusic
from ytmusicapi.auth.types import AuthType

from music_cli.provider import Item, YouTubeMusic, login_headers
from music_cli.storage import UserError


def test_selected_browser_account_headers_are_accepted_by_real_library():
    headers = login_headers("__Secure-3PAPISID=synthetic", "SAPISIDHASH 1_test", "2", "brand123")
    api = YTMusic(headers)
    assert api.auth_type == AuthType.BROWSER
    assert headers["x-goog-authuser"] == "2"
    assert headers["x-goog-pageid"] == "brand123"


def test_header_injection_rejected():
    with pytest.raises(UserError):
        login_headers("cookie\r\nInjected: header", "SAPISIDHASH test", "0")


def test_search_keeps_exact_ids_and_filters_unavailable_results():
    service = YouTubeMusic()
    service._call = Mock(
        return_value=[
            {"videoId": "abcdefghijk", "title": "曲", "artists": [{"name": "歌手"}]},
            {"videoId": "01234567890", "isAvailable": False},
            {"title": "unavailable"},
        ]
    )
    assert service.search("test") == [Item("abcdefghijk", "曲", "歌手")]


def test_guest_library_fails_with_login_guidance():
    with pytest.raises(UserError, match="ログイン"):
        YouTubeMusic().library()


def test_raw_upstream_error_is_not_displayed(monkeypatch):
    monkeypatch.setattr(
        "music_cli.provider.YTMusic", Mock(side_effect=RuntimeError("COOKIE=secret"))
    )
    with pytest.raises(UserError) as captured:
        YouTubeMusic().search("test")
    assert "secret" not in str(captured.value)
