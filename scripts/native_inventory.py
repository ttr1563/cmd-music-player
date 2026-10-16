"""Record the exact native inputs to a preview; this is not license clearance."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from importlib.metadata import version
from pathlib import Path


def inventory(app: Path) -> dict:
    if not app.is_dir():
        raise SystemExit(f"Application directory does not exist: {app}")
    libraries = []
    for path in sorted(app.rglob("*")):
        if path.is_file() and (
            path.suffix.lower() in {".dll", ".pyd", ".dylib", ".so"} or ".so." in path.name
        ):
            with path.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            libraries.append({"path": path.relative_to(app).as_posix(), "sha256": digest})
    return {
        "license_review": "pending; do not publish this preview as a cleared binary",
        "platform": sys.platform,
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "packages": {name: version(name) for name in ("av", "miniaudio", "pyinstaller")},
        "native_libraries": libraries,
    }


if __name__ == "__main__":
    app, output = map(Path, sys.argv[1:])
    output.write_text(json.dumps(inventory(app), indent=2) + "\n", encoding="utf-8")
