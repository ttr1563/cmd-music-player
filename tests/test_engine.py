import asyncio
import io
import multiprocessing
import queue
import time
from unittest.mock import Mock

import av
import miniaudio
import pytest
from test_audio import wav_bytes

from music_cli.audio import RATE, AudioSession, audio_worker
from music_cli.engine import AudioEngine
from music_cli.storage import UserError


class NullSession(AudioSession):
    def __init__(self, url, volume):
        # Real decoding and a real device callback, but no physical audio output.
        super().__init__(
            url,
            volume,
            opener=lambda _: av.open(io.BytesIO(wav_bytes(2))),
            device_factory=lambda: miniaudio.PlaybackDevice(
                output_format=miniaudio.SampleFormat.FLOAT32,
                nchannels=2,
                sample_rate=RATE,
                buffersize_msec=50,
                backends=[miniaudio.Backend.NULL],
                thread_prio=miniaudio.ThreadPriority.NORMAL,
            ),
        )


def null_worker(connection):
    audio_worker(connection, session_factory=NullSession)


async def wait_for_end(engine, timeout=4):
    deadline = time.monotonic() + timeout
    while not engine.ended:
        engine.pump()
        if time.monotonic() > deadline:
            raise AssertionError("audio worker did not finish")
        await asyncio.sleep(0.02)


async def test_native_worker_plays_pauses_seeks_and_reaps_without_mpv():
    events = queue.SimpleQueue()
    engine = AudioEngine(events, 70, worker=null_worker)
    try:
        await engine.load("https://r1.googlevideo.com/synthetic")
        process = engine.process
        pid = process.pid
        engine.command("cycle", "pause")
        engine.command("set_property", "volume", 30)
        await asyncio.sleep(0.2)
        assert engine.paused and not engine.ended
        engine.command("seek", 1.6, "relative")
        engine.command("cycle", "pause")
        await wait_for_end(engine)
        assert events.get_nowait()["reason"] == "eof"
        assert engine.volume == 30
    finally:
        await engine.close()
    assert engine.process is None and engine.connection is None
    assert pid not in [p.pid for p in multiprocessing.active_children()]


async def test_native_worker_cancellation_closes_process_and_pipe():
    engine = AudioEngine(queue.SimpleQueue(), 70, worker=null_worker)
    await engine.load("https://r1.googlevideo.com/synthetic")
    pid = engine.process.pid
    engine.command("stop")
    await asyncio.gather(engine.close(), engine.close())
    assert engine.connection is None and engine.process is None
    assert pid not in [p.pid for p in multiprocessing.active_children()]


async def test_private_pipe_carries_url_not_process_arguments(monkeypatch):
    context = Mock()
    parent = Mock()
    child = Mock()
    context.Pipe.return_value = parent, child
    process = context.Process.return_value
    process.pid = 123
    process.exitcode = None
    process.is_alive.return_value = False
    parent.poll.side_effect = [True, False]
    parent.recv.return_value = {"event": "ready"}
    monkeypatch.setattr("music_cli.engine.multiprocessing.get_context", lambda _: context)
    engine = AudioEngine(queue.SimpleQueue(), 70)
    await engine.load("https://r1.googlevideo.com/signed-secret")
    assert "signed-secret" not in repr(context.Process.call_args)
    parent.send.assert_any_call({"url": "https://r1.googlevideo.com/signed-secret", "volume": 70})
    await engine.close()
    process.close.assert_called_once()


async def test_engine_rejects_non_https_or_local_media_before_start():
    engine = AudioEngine(queue.SimpleQueue(), 70)
    with pytest.raises(ValueError):
        await engine.load("file:///etc/passwd")
    assert engine.process is None


def test_worker_crash_is_one_safe_error_event():
    engine = AudioEngine(queue.SimpleQueue(), 70)
    engine.connection = Mock()
    engine.connection.poll.return_value = True
    engine.connection.recv.side_effect = EOFError
    engine.pump()
    assert engine.events.get_nowait()["reason"] == "error"
    engine.pump()
    assert engine.events.empty()


async def test_device_failure_reaches_the_terminal_without_raw_details(monkeypatch):
    context = Mock()
    parent, child = Mock(), Mock()
    context.Pipe.return_value = parent, child
    context.Process.return_value.pid = 123
    context.Process.return_value.exitcode = None
    context.Process.return_value.is_alive.return_value = False
    parent.poll.side_effect = [True, False]
    parent.recv.return_value = {"event": "end", "reason": "error", "code": "device_failed"}
    monkeypatch.setattr("music_cli.engine.multiprocessing.get_context", lambda _: context)
    engine = AudioEngine(queue.SimpleQueue(), 70)
    with pytest.raises(UserError, match="出力"):
        await engine.load("https://r1.googlevideo.com/signed-secret")
    assert engine.process is None and engine.connection is None


async def test_stuck_worker_is_terminated_then_killed_and_reaped():
    engine = AudioEngine(queue.SimpleQueue(), 70)
    process = Mock(pid=123)
    process.is_alive.side_effect = [True, True, False]
    engine.process = process
    await engine.close()
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    process.close.assert_called_once()
    assert engine.process is None
