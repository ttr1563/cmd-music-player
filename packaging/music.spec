"""One-directory bundle: preserve native libraries and upstream package notices."""

import os
from importlib.metadata import distribution
from pathlib import Path

from packaging.requirements import Requirement
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).parent
staging = Path(os.environ["MUSIC_BINARY_STAGING"])
datas = [(str(staging / "notices"), "notices")]
binaries = [(str(staging / "runtime" / ("deno.exe" if os.name == "nt" else "deno")), "runtime")]
hiddenimports = []
for package in ("ytmusicapi", "yt_dlp", "yt_dlp_ejs", "av", "miniaudio", "textual", "certifi"):
    data, native, hidden = collect_all(package)
    datas += data
    binaries += native
    hiddenimports += hidden

# Include metadata and license files for the runtime dependency closure, not dev tools.
pending = ["music-cli-local"]
seen = set()
while pending:
    name = pending.pop()
    dist = distribution(name)
    name = dist.metadata["Name"]
    if name in seen:
        continue
    seen.add(name)
    datas += copy_metadata(name)
    for requirement in dist.requires or []:
        req = Requirement(requirement)
        if req.marker is None or any(req.marker.evaluate({"extra": extra}) for extra in ("", "default")):
            pending.append(req.name)

a = Analysis(
    [str(root / "packaging" / "entrypoint.py")],
    pathex=[str(root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "tkinter", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="fest", console=True,
    strip=False, upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="fest")
