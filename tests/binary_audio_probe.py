"""Test-only code executed inside a frozen spawn child, never bundled in fest."""

import io

import av
import miniaudio
from ytmusicapi import YTMusic

from music_cli.audio import RATE, AudioSession, PCMBuffer, audio_worker


class ProbeBuffer(PCMBuffer):
    nonzero_pcm = False

    def read(self, frames):
        data = super().read(frames)
        self.nonzero_pcm |= any(data)
        return data


def probe(connection):
    YTMusic(requests_session=False)
    encoded = connection.recv()

    class ProbeSession(AudioSession):
        def __init__(self, url, volume):
            super().__init__(
                url,
                volume,
                opener=lambda _: av.open(io.BytesIO(encoded)),
                device_factory=lambda: miniaudio.PlaybackDevice(
                    output_format=miniaudio.SampleFormat.FLOAT32,
                    nchannels=2,
                    sample_rate=RATE,
                    buffersize_msec=50,
                    backends=[miniaudio.Backend.NULL],
                    thread_prio=miniaudio.ThreadPriority.NORMAL,
                ),
            )
            self.buffer = ProbeBuffer()
            self.buffer.volume = volume

        def seek(self, offset):
            super().seek(offset)
            connection.send(
                {"event": "probe-seek", "paused": self.buffer.paused, "volume": self.buffer.volume}
            )

        def close(self):
            super().close()
            connection.send(
                {
                    "event": "probe-closed",
                    "decoder_alive": self.decoder is not None and self.decoder.is_alive(),
                    "device_closed": self.device is None,
                    "position": self.buffer.position,
                    "nonzero_pcm": self.buffer.nonzero_pcm,
                }
            )

    audio_worker(connection, session_factory=ProbeSession)


# The parent supplies this single private pipe through multiprocessing, not argv.
if __name__ == "__frozen_audio_probe__":
    probe(globals()["connection"])
