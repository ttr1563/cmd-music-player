"""Maintainer build: run on the destination OS with Python 3.12 installed."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import tomllib
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    machine = platform.machine().lower()
    arch = {"aarch64": "arm64", "amd64": "x86_64"}.get(machine, machine)
    target = f"{sys.platform}-{arch}"
    manifest = json.loads((ROOT / "packaging/deno.json").read_text())
    if target not in manifest["targets"]:
        raise SystemExit(f"Unsupported native preview target: {target}")
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Build with Python 3.12")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    with tempfile.TemporaryDirectory(prefix="fest-native-build-") as temporary:
        work = Path(temporary)
        tools = work / "tools"
        venv.create(tools, with_pip=True)
        bin_dir = "Scripts" if os.name == "nt" else "bin"
        python_name = "python.exe" if os.name == "nt" else "python"
        uv_name = "uv.exe" if os.name == "nt" else "uv"
        env = dict(
            os.environ,
            UV_PROJECT_ENVIRONMENT=str(work / "env"),
            UV_CACHE_DIR=str(work / "cache"),
            PYTHONUTF8="1",
        )
        if target == "darwin-x86_64":
            env["OPENSSL_STATIC"] = "1"

        def run(*args: str | Path, timeout: int = 600) -> None:
            subprocess.run(args, cwd=ROOT, env=env, check=True, timeout=timeout)

        run(
            tools / bin_dir / python_name,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--only-binary=:all:",
            "uv==0.13.1",
        )
        run(
            tools / bin_dir / uv_name,
            "sync",
            "--locked",
            "--group",
            "binary",
            "--python",
            sys.executable,
            "--no-build-package",
            "av",
            "--no-build-package",
            "miniaudio",
        )
        python = work / "env" / bin_dir / python_name
        run(python, "-m", "pytest", "-q", f"--basetemp={work / 'pytest'}")
        run(python, "scripts/build_binary.py")
        run(
            python,
            "scripts/native_inventory.py",
            ROOT / "dist" / f"binary-{target}" / "fest",
            ROOT / "dist" / f"fest-{version}-{target}.native.json",
        )
        suffix = ".zip" if os.name == "nt" else ".tar.gz"
        archive = ROOT / "dist" / f"fest-{version}-{target}{suffix}"
        unpacked = work / "unpacked"
        shutil.unpack_archive(archive, unpacked)
        executable = unpacked / "fest" / ("fest.exe" if os.name == "nt" else "fest")
        run(python, "tests/binary_smoke.py", executable)


if __name__ == "__main__":
    main()
