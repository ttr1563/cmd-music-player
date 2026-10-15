import asyncio
import json
import os
from unittest.mock import AsyncMock, Mock

import pytest

from music_cli.player import Player
from music_cli.provider import Item
from music_cli.storage import UserError


def test_start_creates_in_package_engine_without_external_binary(monkeypatch):
    factory = Mock()
    monkeypatch.setattr("music_cli.player.AudioEngine", factory)
    player = Player()
    player.start()
    player.start()
    factory.assert_called_once_with(player.events, 70)


async def test_resolution_sends_credentials_via_stdin_not_process_arguments(monkeypatch):
    process = Mock(returncode=0)
    process.communicate = AsyncMock(
        return_value=(json.dumps({"url": "https://cdn/test"}).encode(), b"")
    )
    process.wait = AsyncMock()
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr("music_cli.player.asyncio.create_subprocess_exec", spawn)
    player = Player({"cookie": "private-cookie"})
    player.engine = Mock(load=AsyncMock())
    await player.play(Item("abcdefghijk", "test"))
    assert "private-cookie" not in repr(spawn.call_args)
    assert b"private-cookie" in process.communicate.call_args.args[0]
    player.engine.load.assert_awaited_once_with("https://cdn/test")


@pytest.mark.skipif(os.name == "nt", reason="POSIX process group")
async def test_cancelled_extraction_kills_and_reaps_child(monkeypatch):
    started = asyncio.Event()
    process = Mock(returncode=None, pid=123456)
    kill_group = Mock()
    monkeypatch.setattr("music_cli.player.os.killpg", kill_group)

    async def hang(_):
        started.set()
        await asyncio.sleep(60)

    process.communicate = hang
    process.wait = AsyncMock()
    monkeypatch.setattr(
        "music_cli.player.asyncio.create_subprocess_exec", AsyncMock(return_value=process)
    )
    player = Player()
    task = asyncio.create_task(player.play(Item("abcdefghijk", "test")))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    kill_group.assert_called_once()
    process.wait.assert_awaited_once()
    assert player.resolver is None


async def test_failed_extraction_does_not_play_another_video(monkeypatch):
    process = Mock(returncode=1)
    process.communicate = AsyncMock(return_value=(b'{"error":"private raw error"}', b""))
    process.wait = AsyncMock()
    monkeypatch.setattr(
        "music_cli.player.asyncio.create_subprocess_exec", AsyncMock(return_value=process)
    )
    player = Player()
    player.engine = Mock(load=AsyncMock())
    with pytest.raises(UserError) as captured:
        await player.play(Item("abcdefghijk", "test"))
    assert "private raw error" not in str(captured.value)
    player.engine.load.assert_not_awaited()


@pytest.mark.skipif(os.name == "nt", reason="POSIX process group")
async def test_close_reaps_resolver_and_native_engine(monkeypatch):
    player = Player({"cookie": "secret"})
    kill_group = Mock()
    monkeypatch.setattr("music_cli.player.os.killpg", kill_group)
    player.resolver = Mock(returncode=None, pid=123456)
    player.resolver.wait = AsyncMock()
    child = player.resolver
    player.engine = Mock(close=AsyncMock())
    engine = player.engine
    await player.close()
    kill_group.assert_called_once()
    child.wait.assert_awaited_once()
    engine.close.assert_awaited_once()
    assert player.headers is None


async def test_windows_cleanup_requests_only_owned_process_tree(monkeypatch):
    from types import SimpleNamespace

    process = Mock(returncode=None, pid=123456)
    process.wait = AsyncMock()
    killer = Mock(returncode=0, wait=AsyncMock())
    spawn = AsyncMock(return_value=killer)
    monkeypatch.setattr(
        "music_cli.player.os",
        SimpleNamespace(
            name="nt",
            path=os.path,
            environ={"SystemRoot": r"C:\Windows"},
        ),
    )
    monkeypatch.setattr("music_cli.player.asyncio.create_subprocess_exec", spawn)
    await Player._finish_resolver(process)
    assert spawn.call_args.args[1:] == ("/PID", "123456", "/T", "/F")
    process.wait.assert_awaited_once()


async def test_process_spawn_failure_is_safe_and_actionable(monkeypatch):
    monkeypatch.setattr(
        "music_cli.player.asyncio.create_subprocess_exec",
        AsyncMock(
            side_effect=OSError("raw process error"),
        ),
    )
    with pytest.raises(UserError, match="起動できません"):
        await Player().play(Item("abcdefghijk", "test"))


async def test_timeout_cleans_child_and_does_not_start_playback(monkeypatch):
    process = Mock(returncode=None, communicate=Mock(return_value=None))
    monkeypatch.setattr(
        "music_cli.player.asyncio.create_subprocess_exec",
        AsyncMock(
            return_value=process,
        ),
    )
    monkeypatch.setattr("music_cli.player.asyncio.wait_for", AsyncMock(side_effect=TimeoutError))
    player = Player()
    player._finish_resolver = AsyncMock()
    player.engine = Mock(load=AsyncMock())
    with pytest.raises(UserError, match="タイムアウト"):
        await player.play(Item("abcdefghijk", "test"))
    player._finish_resolver.assert_awaited_once_with(process)
    player.engine.load.assert_not_awaited()
