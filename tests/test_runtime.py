import sys

import pytest

from music_cli.runtime import js_runtimes, resolver_command, runtime_description
from music_cli.storage import UserError


def test_source_uses_python_module_and_supported_runtimes(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert resolver_command() == [sys.executable, "-m", "music_cli.resolver"]
    assert js_runtimes() == {"deno": {}, "node": {}}


@pytest.mark.parametrize("platform,name", [("darwin", "deno"), ("win32", "deno.exe")])
def test_frozen_uses_only_bundled_runtime_and_self_dispatch(tmp_path, monkeypatch, platform, name):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr("music_cli.runtime.shutil.which", lambda _: pytest.fail("searched PATH"))
    (tmp_path / "runtime").mkdir()
    bundled = tmp_path / "runtime" / name
    bundled.touch()
    assert resolver_command() == [sys.executable, "--internal-resolver"]
    assert js_runtimes() == {"deno": {"path": str(bundled)}}
    assert runtime_description() == str(bundled)


def test_missing_bundled_runtime_reports_damaged_installation(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    with pytest.raises(UserError, match="再展開"):
        js_runtimes()
