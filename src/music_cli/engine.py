"""Cross-platform, in-package audio process controlled through a private pipe."""

from __future__ import annotations

import asyncio
import multiprocessing
import queue
import time

from .audio import audio_worker
from .storage import UserError
from .transport import validate_url

ERRORS = {
    "device_failed": "音声出力を開始できません。OSの出力先・デバイスを確認してください。",
    "seek_failed": "この曲をシークできませんでした。曲を選び直して再生してください。",
    "stream_failed": "音声の受信・デコードに失敗しました。曲を選び直してください。",
}


class AudioEngine:
    def __init__(self, events: queue.SimpleQueue, volume: int, *, worker=audio_worker):
        self.events = events
        self.volume = volume
        self.process = None
        self.connection = None
        self.ready = False
        self.ended = False
        self.error: str | None = None
        self.paused = False
        self._close_lock = asyncio.Lock()
        self.worker = worker

    async def load(self, url: str) -> None:
        validate_url(url)
        await self.close()
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        self.connection = parent
        self.process = context.Process(target=self.worker, args=(child,), daemon=True)
        self.ready = self.ended = self.paused = False
        self.error = None
        try:
            self.process.start()
            child.close()
            parent.send({"url": url, "volume": self.volume})
            deadline = time.monotonic() + 25
            while not self.ready:
                self.pump()
                if self.error:
                    raise UserError(self.error)
                if self.ended:
                    raise UserError("音声を開始できませんでした。曲を選び直してください。")
                if time.monotonic() >= deadline:
                    raise UserError("音声の準備がタイムアウトしました。接続を確認してください。")
                await asyncio.sleep(0.02)
        except BaseException:
            child.close()
            await self.close()
            raise

    def pump(self) -> None:
        if self.ended:
            if self.process is not None and self.process.exitcode is not None:
                self.process.close()
                self.process = None
                self.connection.close()
                self.connection = None
            return
        if self.connection is None:
            return
        try:
            while self.connection.poll():
                message = self.connection.recv()
                if message["event"] == "ready":
                    self.ready = True
                elif message["event"] == "end":
                    self.ended = True
                    if message["reason"] == "error":
                        self.error = ERRORS.get(message.get("code"), ERRORS["stream_failed"])
                    self.events.put({"reason": message["reason"], "message": self.error})
        except (EOFError, OSError):
            if not self.ended:
                self.error = ERRORS["stream_failed"]
                self.ended = True
                self.events.put({"reason": "error", "message": self.error})
        if self.process is not None and self.process.exitcode is not None and not self.ended:
            self.error = ERRORS["stream_failed"]
            self.ended = True
            self.events.put({"reason": "error", "message": self.error})

    def command(self, name: str, *args) -> None:
        if name == "set_property" and args[0] == "volume":
            self.volume = args[1]
        if self.connection is None or self.ended:
            return
        if name == "stop":
            payload = {"op": "stop"}
            self.ended = True
        elif name == "cycle" and args[0] == "pause":
            self.paused = not self.paused
            payload = {"op": "pause", "value": self.paused}
        elif name == "set_property" and args[0] == "volume":
            payload = {"op": "volume", "value": self.volume}
        elif name == "seek":
            payload = {"op": "seek", "value": args[0]}
        else:
            raise ValueError("unsupported audio operation")
        try:
            self.connection.send(payload)
        except (BrokenPipeError, OSError) as error:
            raise UserError(ERRORS["stream_failed"]) from error

    async def close(self) -> None:
        async with self._close_lock:
            self._close()

    def _close(self) -> None:
        if self.connection is not None:
            try:
                self.connection.send({"op": "stop"})
            except (BrokenPipeError, OSError):
                pass
            self.connection.close()
            self.connection = None
        if self.process is not None:
            if self.process.pid is not None:
                # Keep ownership through cancellation. The normal grace period is
                # 0.3s; terminate/kill waits only apply to an unresponsive worker.
                self.process.join(0.3)
                if self.process.is_alive():
                    self.process.terminate()
                    self.process.join(2)
                if self.process.is_alive():
                    self.process.kill()
                    self.process.join(2)
                if self.process.is_alive():
                    raise UserError(
                        "再生processを終了できません。OSのprocess一覧を確認してください。"
                    )
            self.process.close()
            self.process = None
        self.ended = True
