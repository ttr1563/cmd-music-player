import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture
def builder(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "binary_builder", Path(__file__).resolve().parents[1] / "scripts/build_binary.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(module.sys, "platform", "linux")
    (tmp_path / "packaging").mkdir()
    (tmp_path / "packaging/deno.json").write_text(
        json.dumps(
            {"version": "2.9.7", "targets": {"linux-x86_64": ["x86_64-unknown-linux-gnu", "bad"]}}
        )
    )
    (tmp_path / "pyproject.toml").write_text('[project]\nversion="0.2.0"\n')
    return module


def test_unsupported_platform_stops_before_network(builder, monkeypatch):
    monkeypatch.setattr(builder.platform, "machine", lambda: "arm64")
    fetch = Mock()
    monkeypatch.setattr(builder, "download", fetch)
    with pytest.raises(SystemExit, match="Unsupported"):
        builder.main()
    fetch.assert_not_called()


def test_existing_binary_is_not_overwritten(builder, monkeypatch):
    (builder.ROOT / "dist/binary-linux-x86_64").mkdir(parents=True)
    fetch = Mock()
    monkeypatch.setattr(builder, "download", fetch)
    with pytest.raises(SystemExit, match="Output exists"):
        builder.main()
    fetch.assert_not_called()


def test_checksum_failure_never_executes_downloaded_content(builder, monkeypatch):
    monkeypatch.setattr(builder, "download", lambda _: b"modified-runtime")
    execute = Mock()
    monkeypatch.setattr(builder.subprocess, "run", execute)
    with pytest.raises(SystemExit, match="checksum mismatch"):
        builder.main()
    execute.assert_not_called()
