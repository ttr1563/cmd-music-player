import io
from unittest.mock import Mock

import pytest
from test_audio import encoded_audio

from music_cli.audio import open_stream
from music_cli.transport import READ_BYTES, MediaReader


def response(data, *, offset=0, code=200, headers=None):
    result = Mock(status_code=code, is_redirect=False)
    result.headers = headers or {"Content-Length": str(len(data))}
    body = io.BytesIO(data[offset:])
    result.raw.read.side_effect = lambda size, **_: body.read(size)
    return result


def test_https_certificate_hostname_verification_and_bounded_reads():
    session = Mock()
    session.get.return_value = response(b"x" * (READ_BYTES * 2))
    with MediaReader("https://r1.googlevideo.com/signed", session=session) as reader:
        assert len(reader.read(READ_BYTES * 4)) == READ_BYTES
        assert reader.tell() == READ_BYTES
        options = session.get.call_args.kwargs
        assert options["verify"] is True
        assert options["allow_redirects"] is False
        assert options["timeout"] == (10, 5)
        assert options["headers"] == {"Accept-Encoding": "identity"}
    session.close.assert_called()


def test_seek_uses_verified_byte_ranges_and_preserves_position():
    session = Mock()
    initial = response(b"0123456789")
    ranged = response(b"0123456789", offset=5, code=206, headers={"Content-Range": "bytes 5-9/10"})
    session.get.side_effect = [initial, ranged]
    with MediaReader("https://r1.googlevideo.com/signed", session=session) as reader:
        assert reader.seek(5) == 5
        assert reader.read(2) == b"56"
        assert session.get.call_args.kwargs["headers"]["Range"] == "bytes=5-"
        assert reader.seek(0, io.SEEK_END) == 10
        assert reader.read() == b""
    initial.close.assert_called()
    ranged.close.assert_called()


@pytest.mark.parametrize("range_header", ["bytes 0-9/10", "bytes 5-12/10", "invalid"])
def test_wrong_range_is_rejected_instead_of_playing_wrong_position(range_header):
    session = Mock()
    session.get.side_effect = [
        response(b"0123456789"),
        response(
            b"0123456789",
            code=206,
            headers={"Content-Range": range_header},
        ),
    ]
    with MediaReader("https://r1.googlevideo.com/signed", session=session) as reader:
        with pytest.raises(OSError, match="range"):
            reader.seek(5)


def test_redirect_cannot_escape_to_local_or_unverified_source():
    session = Mock()
    redirect = Mock(is_redirect=True, headers={"Location": "http://127.0.0.1/private"})
    session.get.return_value = redirect
    with pytest.raises(ValueError):
        MediaReader("https://r1.googlevideo.com/signed", session=session)
    session.get.assert_called_once()
    redirect.close.assert_called()
    session.close.assert_called()


def test_truncated_connection_does_not_look_like_normal_song_end():
    session = Mock()
    session.get.return_value = response(b"short", headers={"Content-Length": "100"})
    with MediaReader("https://r1.googlevideo.com/signed", session=session) as reader:
        assert reader.read(10) == b"short"
        with pytest.raises(OSError, match="prematurely"):
            reader.read(10)


@pytest.mark.parametrize(("codec", "format"), [("aac", "mp4"), ("libopus", "webm")])
def test_decoder_uses_file_like_transport_without_ffmpeg_network_access(monkeypatch, codec, format):
    data = encoded_audio(codec, format)
    session = Mock()

    def get(url, **options):
        range_header = options["headers"].get("Range")
        if range_header:
            offset = int(range_header[6:-1])
            return response(
                data,
                offset=offset,
                code=206,
                headers={
                    "Content-Range": f"bytes {offset}-{len(data) - 1}/{len(data)}",
                },
            )
        return response(data)

    session.get.side_effect = get
    monkeypatch.setattr(
        "music_cli.audio.MediaReader", lambda url: MediaReader(url, session=session)
    )
    with open_stream("https://r1.googlevideo.com/synthetic") as container:
        assert sum(frame.samples for frame in container.decode(audio=0)) > 1000


def test_unknown_length_is_streamable_but_not_seekable():
    session = Mock()
    item = response(b"unknown")
    item.headers = {}
    session.get.return_value = item
    with MediaReader("https://r1.googlevideo.com/signed", session=session) as reader:
        assert not reader.seekable()
        assert reader.read(10) == b"unknown"
        assert reader.read(10) == b""
        with pytest.raises(OSError):
            reader.seek(0)
