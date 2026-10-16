import array
import io
import threading
import time
import wave

import av
import pytest

from music_cli.audio import BUFFER_BYTES, FRAME_BYTES, RATE, AudioSession, PCMBuffer


def wav_bytes(seconds=0.3):
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setparams((2, 2, RATE, 0, "NONE", "not compressed"))
        writer.writeframes(array.array("h", [8000, -8000] * int(RATE * seconds)).tobytes())
    return output.getvalue()


class FakeDevice:
    def start(self, stream):
        self.stream = stream

    def close(self):
        self.closed = True


def test_buffer_pause_volume_underrun_and_position():
    buffer = PCMBuffer()
    buffer.put(array.array("f", [0.5, -0.5] * 4).tobytes(), 0)
    buffer.paused = True
    assert buffer.read(2) == bytes(16)
    assert buffer.size == 32 and buffer.position == 0
    buffer.paused = False
    buffer.volume = 50
    assert array.array("f", buffer.read(2)).tolist() == [0.25, -0.25] * 2
    assert buffer.position == 2 / RATE
    buffer.volume = 0
    assert buffer.read(4) == bytes(32)
    assert buffer.size == 0 and buffer.position == 4 / RATE


def test_decoder_backpressure_is_bounded_and_stop_wakes_producer():
    buffer = PCMBuffer()
    buffer.put(bytes(BUFFER_BYTES), 0)
    result = []
    producer = threading.Thread(target=lambda: result.append(buffer.put(bytes(8), 0)))
    producer.start()
    assert buffer.size == BUFFER_BYTES
    buffer.close()
    producer.join(1)
    assert not producer.is_alive() and result == [False]


def test_seek_clears_old_audio_and_rejects_stale_decoder_frames():
    buffer = PCMBuffer()
    buffer.put(bytes(100 * FRAME_BYTES), 0)
    generation = buffer.reset(10)
    assert not buffer.put(b"old", 0)
    assert buffer.size == 0 and buffer.position == 10
    assert buffer.put(bytes(16), generation)


def test_eof_is_reported_after_last_buffer_has_been_consumed():
    buffer = PCMBuffer()
    buffer.volume = 100
    buffer.put(bytes(FRAME_BYTES), 0)
    buffer.finished = True
    buffer.read(1)
    assert buffer.drained_at is None
    buffer.read(1)
    assert buffer.drained_at is not None


def encoded_audio(codec, format, seconds=0.3):
    encoded = io.BytesIO()
    with (
        av.open(io.BytesIO(wav_bytes(seconds))) as source,
        av.open(encoded, "w", format=format) as output,
    ):
        stream = output.add_stream(codec, rate=RATE)
        stream.layout = "stereo"
        resampler = av.AudioResampler(
            format=av.Codec(codec, "w").audio_formats[0].name, layout="stereo", rate=RATE
        )
        for frame in source.decode(audio=0):
            for converted in resampler.resample(frame):
                for packet in stream.encode(converted):
                    output.mux(packet)
        for packet in stream.encode(None):
            output.mux(packet)
    return encoded.getvalue()


@pytest.mark.parametrize(("codec", "format"), [("aac", "mp4"), ("libopus", "webm")])
def test_real_aac_and_opus_decoders_feed_stereo_pcm(codec, format):
    encoded = encoded_audio(codec, format)
    device = FakeDevice()
    session = AudioSession(
        "synthetic",
        100,
        opener=lambda _: av.open(io.BytesIO(encoded)),
        device_factory=lambda: device,
    )
    try:
        session.start()
        assert session.ready.wait(2)
        received = bytearray()
        deadline = time.monotonic() + 2
        while session.buffer.drained_at is None and time.monotonic() < deadline:
            received.extend(device.stream.send(480))
            time.sleep(0.001)
        assert session.error is None
        assert session.buffer.drained_at is not None
        assert max(array.array("f", received)) > 0.1
    finally:
        session.close()
    assert device.closed
    assert not session.decoder.is_alive()


def test_decode_failure_never_exposes_url_or_exception_text():
    def fail(_):
        raise RuntimeError("https://private/signed-url")

    session = AudioSession("private", 50, opener=fail, device_factory=FakeDevice)
    try:
        session.start()
        session.decoder.join(1)
        assert session.error == "stream_failed"
    finally:
        session.close()
