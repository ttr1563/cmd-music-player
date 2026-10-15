"""Bounded extraction and owned mpv process, with no media files on disk."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid

import python_mpv_jsonipc as mpv

from .provider import Item
from .storage import UserError

mpv.TIMEOUT = 5
logging.getLogger("mpv-jsonipc").addHandler(logging.NullHandler())
logging.getLogger("mpv-jsonipc").propagate = False

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
        self.temporary: tempfile.TemporaryDirectory | None = None
        self.resolver: asyncio.subprocess.Process | None = None
        self.events: queue.SimpleQueue = queue.SimpleQueue()
        self.closed = False
        self._play_lock = asyncio.Lock()

    def start(self) -> None:
        if self.engine is not None:
            return
        executable = shutil.which("mpv")
        if not executable:
            raise UserError("mpvが見つかりません。music doctorで導入方法を確認してください。")
        self.temporary = tempfile.TemporaryDirectory(prefix="music-cli-")
        endpoint = (
            f"music-cli-{uuid.uuid4().hex}"
            if os.name == "nt"
            else os.path.join(self.temporary.name, "mpv.sock")
        )
        try:
            self.engine = mpv.MPV(
                mpv_location=executable,
                ipc_socket=endpoint,
                start_retries=1,
                diagnose_start_failures=False,
                discard_output=True,
                config=False,
                video=False,
                audio_display=False,
                terminal=False,
                idle=True,
                ytdl=False,
                volume=self.volume,
                cache_on_disk=False,
                save_position_on_quit=False,
                input_terminal=False,
                input_default_bindings=False,
                demuxer_max_bytes="16MiB",
                demuxer_max_back_bytes="4MiB",
            )
            self.engine.bind_event("end-file", self.events.put)
        except (mpv.MPVError, OSError, TimeoutError) as error:
            self.close_engine()
            raise UserError(
                "mpvを起動できません。music doctorで実行環境を確認してください。"
            ) from error

    async def play(self, item: Item) -> None:
        async with self._play_lock:
            await self._play(item)

    async def _play(self, item: Item) -> None:
        if self.closed:
            return
        self.command("stop")
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "music_cli.resolver",
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
                self.command("set_property", "pause", False)
                self.command("loadfile", result["url"], "replace")
        except TimeoutError as error:
            raise UserError("再生URLの取得がタイムアウトしました。再選択してください。") from error
        except (ValueError, KeyError) as error:
            raise UserError("再生URLの応答が不正です。") from error
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
            try:
                return self.engine.command(name, *args)
            except (mpv.MPVError, OSError, TimeoutError) as error:
                raise UserError(
                    "再生エンジンとの通信に失敗しました。再起動してください。"
                ) from error

    def close_engine(self) -> None:
        try:
            if self.engine is not None:
                self.engine.terminate()
        finally:
            self.engine = None
            if self.temporary is not None:
                self.temporary.cleanup()
                self.temporary = None

    async def close(self) -> None:
        self.closed = True
        if self.resolver is not None:
            await self._finish_resolver(self.resolver)
            self.resolver = None
        self.close_engine()
        self.headers = None
