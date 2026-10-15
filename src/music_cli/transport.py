"""Verified HTTPS and byte-range reads for the decoder's file-like interface."""

from __future__ import annotations

import io
import re
from urllib.parse import urljoin, urlsplit

import requests

READ_BYTES = 64 * 1024


def validate_url(url: str) -> None:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not host.endswith((".googlevideo.com", ".youtube.com")):
        raise ValueError("unsupported media URL")


class MediaReader(io.RawIOBase):
    def __init__(self, url: str, *, session=None):
        super().__init__()
        self.url = url
        self.session = session or requests.Session()
        self.response = None
        self.position = 0
        self.length: int | None = None
        try:
            validate_url(url)
            self._open(0)
        except BaseException:
            self.close()
            raise

    def _open(self, offset: int) -> None:
        if self.response is not None:
            self.response.close()
            self.response = None
        headers = {"Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        url = self.url
        for _ in range(6):
            validate_url(url)
            response = self.session.get(
                url,
                headers=headers,
                stream=True,
                timeout=(10, 5),
                allow_redirects=False,
                verify=True,
            )
            if response.is_redirect:
                redirected = urljoin(url, response.headers["Location"])
                response.close()
                url = redirected
                continue
            try:
                response.raise_for_status()
                if response.status_code == 206:
                    match = re.fullmatch(
                        r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", "")
                    )
                    if (
                        not match
                        or int(match[1]) != offset
                        or not offset <= int(match[2]) < int(match[3])
                    ):
                        raise OSError("invalid media byte range")
                    length = int(match[3])
                elif response.status_code == 200 and offset == 0:
                    value = response.headers.get("Content-Length")
                    length = int(value) if value is not None else None
                else:
                    raise OSError("media source does not support seeking")
                if self.length is not None and length != self.length:
                    raise OSError("media length changed during playback")
                self.length = length
                self.response = response
                self.position = offset
                return
            except BaseException:
                response.close()
                raise
        raise OSError("too many media redirects")

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return self.length is not None

    def tell(self) -> int:
        return self.position

    def read(self, size: int = -1) -> bytes:
        if self.closed:
            raise ValueError("media reader is closed")
        if size == 0 or (self.length is not None and self.position >= self.length):
            return b""
        amount = READ_BYTES if size < 0 else min(size, READ_BYTES)
        data = self.response.raw.read(amount, decode_content=False)
        if not data and self.length is not None and self.position < self.length:
            raise OSError("media connection ended prematurely")
        self.position += len(data)
        return data

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if not self.seekable():
            raise OSError("media length is unknown")
        if whence == io.SEEK_SET:
            target = offset
        elif whence == io.SEEK_CUR:
            target = self.position + offset
        elif whence == io.SEEK_END:
            target = self.length + offset
        else:
            raise ValueError("invalid seek origin")
        if target < 0:
            raise OSError("negative media offset")
        if target != self.position:
            if target >= self.length:
                self.position = target
            else:
                self._open(target)
        return self.position

    def close(self) -> None:
        if self.response is not None:
            self.response.close()
            self.response = None
        self.session.close()
        super().close()
