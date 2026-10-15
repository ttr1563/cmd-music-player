"""Owned audio worker: decode on one thread, never on the device callback."""

from __future__ import annotations

import array
import collections
import sys
import threading
import time
from contextlib import contextmanager
from multiprocessing.connection import Connection

import av
import miniaudio

from .transport import MediaReader, validate_url

RATE = 48_000
FRAME_BYTES = 8  # Stereo, packed float32.
BUFFER_BYTES = RATE * FRAME_BYTES * 2


@contextmanager
def open_stream(url: str):
    # Requests verifies both certificate and hostname consistently across wheels.
    # Exclude nested network/file protocols in media supplied to FFmpeg.
    with (
        MediaReader(url) as reader,
        av.open(
            reader,
            options={
                "protocol_whitelist": "",
                "probesize": "1048576",
                "analyzeduration": "5000000",
            },
        ) as container,
    ):
        yield container


class PCMBuffer:
    def __init__(self):
        self.condition = threading.Condition()
        self.chunks: collections.deque[bytes] = collections.deque()
        self.size = 0
        self.generation = 0
        self.position = 0.0
        self.paused = False
        self.volume = 70
        self.finished = False
        self.closed = False
        self.drained_at: float | None = None

    def put(self, data: bytes, generation: int) -> bool:
        # Decoder frames can vary in size. Enforce the byte cap for every chunk.
        for offset in range(0, len(data), BUFFER_BYTES):
            chunk = data[offset : offset + BUFFER_BYTES]
            chunk_size = len(chunk)
            with self.condition:
                self.condition.wait_for(
                    lambda chunk_size=chunk_size: (
                        self.closed
                        or generation != self.generation
                        or self.size + chunk_size <= BUFFER_BYTES
                    )
                )
                if self.closed or generation != self.generation:
                    return False
                self.chunks.append(chunk)
                self.size += len(chunk)
        return True

    def read(self, frames: int) -> bytes:
        length = frames * FRAME_BYTES
        result = bytearray()
        with self.condition:
            if not self.paused:
                while self.chunks and len(result) < length:
                    chunk = self.chunks.popleft()
                    take = min(length - len(result), len(chunk))
                    result.extend(chunk[:take])
                    if take < len(chunk):
                        self.chunks.appendleft(chunk[take:])
                    self.size -= take
                self.position += len(result) / (FRAME_BYTES * RATE)
                if not result and self.finished and self.drained_at is None:
                    self.drained_at = time.monotonic()
                self.condition.notify_all()
            volume = self.volume
        result.extend(bytes(length - len(result)))
        if volume == 100:
            return bytes(result)
        if volume == 0:
            return bytes(length)
        samples = array.array("f")
        samples.frombytes(result)
        return array.array("f", (sample * volume / 100 for sample in samples)).tobytes()

    def reset(self, position: float) -> int:
        with self.condition:
            self.generation += 1
            self.position = position
            self.chunks.clear()
            self.size = 0
            self.finished = False
            self.drained_at = None
            self.condition.notify_all()
            return self.generation

    def close(self) -> None:
        with self.condition:
            self.closed = True
            self.chunks.clear()
            self.size = 0
            self.condition.notify_all()


def output_device():
    if sys.platform == "darwin":
        backends = [miniaudio.Backend.COREAUDIO]
    elif sys.platform == "win32":
        backends = [miniaudio.Backend.WASAPI]
    else:
        backends = [miniaudio.Backend.PULSEAUDIO, miniaudio.Backend.ALSA]
    # Exclude the null backend: silently discarding music is not playback.
    return miniaudio.PlaybackDevice(
        output_format=miniaudio.SampleFormat.FLOAT32,
        nchannels=2,
        sample_rate=RATE,
        buffersize_msec=100,
        backends=backends,
        thread_prio=miniaudio.ThreadPriority.NORMAL,
        app_name="cmd-music-player",
    )


class AudioSession:
    def __init__(self, url: str, volume: int, *, opener=open_stream, device_factory=output_device):
        self.url = url
        self.opener = opener
        self.device_factory = device_factory
        self.buffer = PCMBuffer()
        self.buffer.volume = volume
        self.ready = threading.Event()
        self.stopped = threading.Event()
        self.error: str | None = None
        self.pending_seek: tuple[int, float] | None = None
        self.device = None
        self.decoder: threading.Thread | None = None
        self.last_callback = time.monotonic()

    def start(self) -> None:
        self.device = self.device_factory()
        stream = self.samples()
        next(stream)
        self.device.start(stream)
        self.decoder = threading.Thread(target=self.decode, name="music-decode", daemon=True)
        self.decoder.start()

    def samples(self):
        frames = yield b""
        while not self.stopped.is_set():
            self.last_callback = time.monotonic()
            frames = yield self.buffer.read(frames)

    def seek(self, offset: float) -> None:
        with self.buffer.condition:
            position = max(0.0, self.buffer.position + offset)
            generation = self.buffer.reset(position)
            self.pending_seek = (generation, position)
            self.buffer.condition.notify_all()

    @staticmethod
    def pcm_frames(resampler, frame):
        for converted in resampler.resample(frame):
            yield bytes(converted.planes[0])[: converted.samples * FRAME_BYTES]

    def decode(self) -> None:
        try:
            with self.opener(self.url) as container:
                stream = container.streams.audio[0]
                stream.codec_context.thread_count = 1
                decoder = iter(container.decode(stream))
                resampler = av.AudioResampler(format="flt", layout="stereo", rate=RATE)
                generation = self.buffer.generation
                target = 0.0
                while not self.stopped.is_set():
                    with self.buffer.condition:
                        seek, self.pending_seek = self.pending_seek, None
                    if seek is not None:
                        generation, target = seek
                        try:
                            container.seek(
                                int(target / stream.time_base), stream=stream, backward=True
                            )
                        except (av.FFmpegError, OSError):
                            self.error = "seek_failed"
                            return
                        decoder = iter(container.decode(stream))
                        resampler = av.AudioResampler(format="flt", layout="stereo", rate=RATE)
                    frame = next(decoder, None)
                    if frame is None:
                        for data in self.pcm_frames(resampler, None):
                            self.buffer.put(data, generation)
                        with self.buffer.condition:
                            if generation == self.buffer.generation:
                                self.buffer.finished = True
                            # Remain available for a seek before the device drains.
                            self.buffer.condition.wait_for(
                                lambda: self.stopped.is_set() or self.pending_seek is not None,
                            )
                        continue
                    if (
                        frame.time is not None
                        and frame.time + frame.samples / frame.sample_rate <= target
                    ):
                        continue
                    for data in self.pcm_frames(resampler, frame):
                        if not self.buffer.put(data, generation):
                            break
                        self.ready.set()
        except Exception:
            # Decoder errors may include the signed media URL.
            self.error = "stream_failed"

    def close(self) -> None:
        self.stopped.set()
        self.buffer.close()
        if self.device is not None:
            self.device.close()
            self.device = None
        if self.decoder is not None:
            self.decoder.join(timeout=0.2)
            # The parent owns and reaps this worker if native I/O is still blocked.


def audio_worker(connection: Connection, *, session_factory=AudioSession) -> None:
    av.logging.set_level(-8)  # FFmpeg AV_LOG_QUIET; raw logs can contain signed URLs.
    session = None
    try:
        payload = connection.recv()
        validate_url(payload["url"])
        session = session_factory(payload["url"], payload["volume"])
        try:
            session.start()
        except miniaudio.MiniaudioError:
            connection.send({"event": "end", "reason": "error", "code": "device_failed"})
            return
        announced = False
        while True:
            if connection.poll(0.02):
                command = connection.recv()
                match command["op"]:
                    case "stop":
                        return
                    case "pause":
                        with session.buffer.condition:
                            session.buffer.paused = command["value"]
                    case "volume":
                        with session.buffer.condition:
                            session.buffer.volume = command["value"]
                    case "seek":
                        session.seek(command["value"])
            if session.error:
                connection.send({"event": "end", "reason": "error", "code": session.error})
                return
            if time.monotonic() - session.last_callback > 2:
                connection.send({"event": "end", "reason": "error", "code": "device_failed"})
                return
            if session.ready.is_set() and not announced:
                connection.send({"event": "ready"})
                announced = True
            # Give the last device buffer time to play before advancing the queue.
            if session.buffer.drained_at and time.monotonic() - session.buffer.drained_at >= 0.15:
                connection.send({"event": "end", "reason": "eof"})
                return
    except (EOFError, BrokenPipeError):
        pass
    except Exception:
        try:
            connection.send({"event": "end", "reason": "error", "code": "stream_failed"})
        except (BrokenPipeError, OSError):
            pass
    finally:
        if session is not None:
            session.close()
        connection.close()
