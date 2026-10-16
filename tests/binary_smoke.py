"""Run after building: python tests/binary_smoke.py /absolute/path/to/fest."""

from __future__ import annotations

import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from music_cli.audio import audio_worker


def start_frozen_worker(worker, internal):
    original_path = sys.path
    main_module = sys.modules["__main__"]
    original_file = main_module.__file__
    try:
        sys.frozen = True
        sys.path = [
            str(internal),
            str(internal / "base_library.zip"),
            str(internal / "lib-dynload"),
        ]
        del main_module.__file__
        worker.start()
    finally:
        sys.path = original_path
        del sys.frozen
        main_module.__file__ = original_file


def receive(connection):
    assert connection.poll(15), "Bundled worker did not respond"
    return connection.recv()


def check_frozen_audio(context, internal):
    from test_audio import encoded_audio

    probe = Path(__file__).with_name("binary_audio_probe.py").read_text(encoding="utf-8")
    for codec, container, stop in [
        ("aac", "mp4", False),
        ("libopus", "webm", False),
        ("aac", "mp4", True),
    ]:
        encoded = encoded_audio(codec, container, seconds=2)
        parent, child = context.Pipe()
        # exec is a picklable builtin already available to the frozen interpreter.
        # All probe code and fixtures stay in the test harness, outside the app.
        worker = context.Process(
            target=exec,
            args=(probe, {"__name__": "__frozen_audio_probe__", "connection": child}),
        )
        start_frozen_worker(worker, internal)
        child.close()
        try:
            parent.send(encoded)
            parent.send({"url": "https://r1.googlevideo.com/synthetic", "volume": 70})
            assert receive(parent) == {"event": "ready"}
            parent.send({"op": "pause", "value": True})
            parent.send({"op": "volume", "value": 30})
            parent.send({"op": "seek", "value": 1.6})
            assert receive(parent) == {"event": "probe-seek", "paused": True, "volume": 30}
            assert not parent.poll(0.1), "Paused audio reached EOF"
            parent.send({"op": "stop"} if stop else {"op": "pause", "value": False})
            if not stop:
                assert receive(parent) == {"event": "end", "reason": "eof"}
            closed = receive(parent)
            assert closed["event"] == "probe-closed"
            assert closed["device_closed"] and not closed["decoder_alive"]
            if not stop:
                assert closed["position"] > 1.6
                assert closed["nonzero_pcm"], "Decoded audio never reached the device callback"
            worker.join(10)
            assert worker.exitcode == 0
        finally:
            if worker.is_alive():
                worker.kill()
                worker.join(5)
            worker.close()
            parent.close()
        print(
            f"Bundled {codec}: pause/volume/seek/{'stop' if stop else 'EOF'}/reap"
            " passed (NULL output)"
        )


def main() -> None:
    executable = Path(sys.argv[1]).resolve()
    internal = executable.parent / "_internal"
    with tempfile.TemporaryDirectory(prefix="music-binary-smoke-") as temporary:
        env = dict(
            os.environ,
            PATH="",
            MUSIC_CLI_HOME=str(Path(temporary) / "data"),
            DENO_DIR=str(Path(temporary) / "deno-cache"),
            DENO_NO_UPDATE_CHECK="1",
        )
        result = subprocess.run(
            [executable, "doctor"], env=env, capture_output=True, text=True, check=True, timeout=30
        )
        assert str(internal / "runtime") in result.stdout, result.stdout
        subprocess.run(
            [executable, "config", "show"], env=env, check=True, capture_output=True, timeout=30
        )
        result = subprocess.run(
            [executable, "--internal-resolver"],
            input='{"id":"invalid"}',
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 1
        assert json.loads(result.stdout) == {"error": "extract_failed"}
        assert not result.stderr
        deno = internal / "runtime" / ("deno.exe" if os.name == "nt" else "deno")
        if sys.platform == "linux":
            # Match the library search path inherited from the frozen parent.
            env["LD_LIBRARY_PATH"] = str(internal)
        result = subprocess.run(
            [deno, "run", "--no-config", "--no-remote", "--no-npm", "-"],
            input='console.log("bundled-js-ok")',
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        assert result.stdout.strip() == "bundled-js-ok"
        subprocess.run(
            [executable, "purge", "--yes"], env=env, check=True, capture_output=True, timeout=30
        )
        assert not (Path(temporary) / "data").exists()

    # Exercise the real bundled spawn dispatcher with an invalid URL. The worker
    # must reject it before opening a network connection or physical audio device.
    context = multiprocessing.get_context("spawn")
    # This test harness is unfrozen: its interpreter flags differ from the app's.
    # Keep its resource tracker on Python; the audio worker uses the actual binary.
    if os.name != "nt":
        from multiprocessing import resource_tracker

        read_fd, write_fd = os.pipe()
        os.close(write_fd)
        try:
            result = subprocess.run(
                [
                    str(executable),
                    "-B",
                    "-S",
                    "-I",
                    "-c",
                    f"from multiprocessing.resource_tracker import main;main({read_fd})",
                ],
                pass_fds=(read_fd,),
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert result.returncode == 0 and not result.stderr, result.stderr
        finally:
            os.close(read_fd)
        resource_tracker.ensure_running()
    context.set_executable(str(executable))
    parent, child = context.Pipe()
    worker = context.Process(target=audio_worker, args=(child,))
    start_frozen_worker(worker, internal)
    child.close()
    try:
        parent.send({"url": "http://invalid.example/", "volume": 0})
        assert parent.poll(15), "Bundled worker did not respond"
        assert parent.recv() == {"event": "end", "reason": "error", "code": "stream_failed"}
        worker.join(10)
        assert worker.exitcode == 0
    finally:
        if worker.is_alive():
            worker.kill()
            worker.join(5)
        worker.close()
        parent.close()
    check_frozen_audio(context, internal)
    print("Standalone doctor/config/purge/resolver/Deno/spawn and offline audio checks passed")


if __name__ == "__main__":
    main()
