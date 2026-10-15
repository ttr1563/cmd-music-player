"""Bounded URL extraction and in-package playback, with no media files on disk."""

from __future__ import annotations

import asyncio
import json
import os
import queue
import signal
import subprocess

from .engine import AudioEngine
from .provider import Item
from .runtime import resolver_command
from .storage import UserError

ERROR_MESSAGES = {
    "login_required": "YouTubeのログイン確認が必要です。music loginで認証を更新してください。",
    "rate_limited": "YouTubeのアクセス制限に達しました。しばらく時間を置いてください。",
    "format_unavailable": "音声形式を取得できません。yt-dlpとJS runtimeの状態を確認してください。",
    "extract_failed": "再生URLを取得できません。接続・認証・yt-dlpを確認してください。",
}


class Player:
    def __init__(self, headers: dict | None = None, volume: int = 70):
        self.headers = headers
        self.volume = volume
        self.engine = None
        self.resolver: asyncio.subprocess.Process | None = None
        self.events: queue.SimpleQueue = queue.SimpleQueue()
        self.closed = False
        self._play_lock = asyncio.Lock()

    def start(self) -> None:
        if self.engine is None:
            self.engine = AudioEngine(self.events, self.volume)

    async def play(self, item: Item) -> None:
        async with self._play_lock:
            await self._play(item)

    async def _play(self, item: Item) -> None:
        if self.closed:
            return
        self.command("stop")
        try:
            process = await asyncio.create_subprocess_exec(
                *resolver_command(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                **(
                    {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                    if os.name == "nt"
                    else {"start_new_session": True}
                ),
            )
        except OSError as error:
            raise UserError(
                "音声取得processを起動できません。実行環境を確認してください。"
            ) from error
        self.resolver = process
        try:
            payload = json.dumps({"id": item.id, "headers": self.headers}).encode()
            stdout, _ = await asyncio.wait_for(process.communicate(payload), timeout=45)
            result = json.loads(stdout)
            if process.returncode != 0:
                code = result.get("error", "extract_failed")
                raise UserError(ERROR_MESSAGES.get(code, ERROR_MESSAGES["extract_failed"]))
            if not self.closed:
                self.start()
                await self.engine.load(result["url"])
        except TimeoutError as error:
            raise UserError("再生URLの取得がタイムアウトしました。再選択してください。") from error
        except (ValueError, KeyError) as error:
            raise UserError("再生URLの応答が不正です。") from error
        except OSError as error:
            raise UserError(
                "音声再生processを起動できません。music doctorで確認してください。"
            ) from error
        finally:
            await self._finish_resolver(process)
            if self.resolver is process:
                self.resolver = None

    @staticmethod
    async def _finish_resolver(process: asyncio.subprocess.Process) -> None:
        if process.returncode is None:
            if os.name == "nt":
                # yt-dlp may have spawned a JS runtime. Terminate the owned tree.
                killer = await asyncio.create_subprocess_exec(
                    os.path.join(
                        os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe"
                    ),
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await asyncio.wait_for(killer.wait(), timeout=5)
                except TimeoutError:
                    killer.kill()
                    await killer.wait()
                if process.returncode is None:
                    process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass  # The owned process group has already exited.
        await process.wait()

    def command(self, name: str, *args):
        if self.engine is not None:
            return self.engine.command(name, *args)

    def poll(self) -> None:
        if self.engine is not None:
            self.engine.pump()

    async def close(self) -> None:
        self.closed = True
        if self.resolver is not None:
            await self._finish_resolver(self.resolver)
            self.resolver = None
        if self.engine is not None:
            await self.engine.close()
            self.engine = None
        self.headers = None
