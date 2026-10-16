"""Build on the destination OS/architecture; only maintainers need Python/uv."""

from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import tomllib
import urllib.request
import zipfile
from importlib.metadata import distribution
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def main() -> None:
    machine = platform.machine().lower()
    arch = {"aarch64": "arm64", "amd64": "x86_64"}.get(machine, machine)
    target = f"{sys.platform}-{arch}"
    manifest = json.loads((ROOT / "packaging/deno.json").read_text())
    if target not in manifest["targets"]:
        raise SystemExit(f"Unsupported binary target: {target}")
    triple, expected = manifest["targets"][target]
    version = manifest["version"]
    package_version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    destination = ROOT / "dist" / f"binary-{target}"
    if destination.exists():
        raise SystemExit(f"Output exists; move it before rebuilding: {destination}")
    with tempfile.TemporaryDirectory(prefix="music-build-") as temporary:
        staging = Path(temporary)
        runtime = staging / "runtime"
        runtime.mkdir()
        notices = staging / "notices"
        notices.mkdir()
        archive = download(
            f"https://github.com/denoland/deno/releases/download/v{version}/deno-{triple}.zip"
        )
        if hashlib.sha256(archive).hexdigest() != expected:
            raise SystemExit("Deno archive checksum mismatch")
        executable = "deno.exe" if os.name == "nt" else "deno"
        with zipfile.ZipFile(io.BytesIO(archive)) as source:
            (runtime / executable).write_bytes(source.read(executable))
        (runtime / executable).chmod(0o755)
        subprocess.run([runtime / executable, "--version"], check=True, timeout=30)
        license_text = download(
            f"https://raw.githubusercontent.com/denoland/deno/v{version}/LICENSE.md"
        )
        if hashlib.sha256(license_text).hexdigest() != (
            "f62497fffecc0852960c8d3e6934b9db86d16396e9b604072e923892cae3a588"
        ):
            raise SystemExit("Deno license checksum mismatch")
        (notices / "DENO-LICENSE.txt").write_bytes(license_text)
        python_license = (
            Path(sys.base_prefix) / "LICENSE.txt"
            if os.name == "nt"
            else Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"
        )
        shutil.copy2(python_license, notices / "PYTHON-LICENSE.txt")
        shutil.copy2(ROOT / "LICENSE", notices / "MUSIC-LICENSE.txt")
        shutil.copy2(ROOT / "README.md", notices / "README.md")
        shutil.copy2(ROOT / "docs/design.md", notices / "DESIGN.md")
        installer = distribution("pyinstaller")
        for file in installer.files or []:
            if file.name == "COPYING.txt":
                shutil.copy2(installer.locate_file(file), notices / "PYINSTALLER-LICENSE.txt")
        shutil.copy2(ROOT / "packaging/THIRD-PARTY.md", notices / "THIRD-PARTY.md")
        shutil.copy2(ROOT / "uv.lock", notices / "DEPENDENCIES.lock")
        env = dict(
            os.environ,
            MUSIC_BINARY_STAGING=str(staging),
            PYINSTALLER_CONFIG_DIR=str(staging / "pyinstaller-cache"),
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--distpath",
                str(destination),
                "--workpath",
                str(staging / "work"),
                str(ROOT / "packaging/music.spec"),
            ],
            cwd=ROOT,
            env=env,
            check=True,
            timeout=600,
        )
        app = destination / "fest"
        # No network, account or sound device required for this installation check.
        subprocess.run(
            [app / ("fest.exe" if os.name == "nt" else "fest"), "--help"], check=True, timeout=30
        )
        name = ROOT / "dist" / f"fest-{package_version}-{target}"
        if os.name == "nt":
            artifact = Path(shutil.make_archive(str(name), "zip", destination, "fest"))
        else:
            artifact = Path(str(name) + ".tar.gz")
            with tarfile.open(artifact, "w:gz", dereference=False) as output:
                output.add(app, arcname="fest")
        with artifact.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        artifact.with_name(artifact.name + ".sha256").write_text(
            f"{digest}  {artifact.name}\n", encoding="utf-8"
        )
        print(f"Built {artifact}")


if __name__ == "__main__":
    main()
