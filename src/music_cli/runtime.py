"""Executable locations shared by source and standalone distributions."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from .storage import UserError


def resolver_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--internal-resolver"]
    return [sys.executable, "-m", "music_cli.resolver"]


def js_runtimes() -> dict:
    if getattr(sys, "frozen", False):
        name = "deno.exe" if sys.platform == "win32" else "deno"
        path = Path(sys._MEIPASS) / "runtime" / name
        if not path.is_file():
            raise UserError("同梱runtimeがありません。配布directory一式を再展開してください。")
        return {"deno": {"path": str(path)}}
    return {"deno": {}, "node": {}}


def runtime_description() -> str:
    runtimes = js_runtimes()
    return runtimes["deno"].get("path") or shutil.which("deno") or shutil.which("node") or "未導入"
