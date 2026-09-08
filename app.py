from __future__ import annotations

import hashlib
import hmac
import importlib.abc
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import traceback
import webbrowser
import zipfile

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
SOURCE_RUNTIME = ROOT / "src"
_SECRET = bytes([99, 17, 131, 109, 13, 162, 212, 211, 209, 23, 186, 168, 87, 15, 123, 114, 247, 179, 222, 198, 209, 227, 251, 122, 115, 154, 150, 86, 125, 181, 8, 83])


def _message(title: str, text: str, error: bool = True) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        (messagebox.showerror if error else messagebox.showinfo)(title, text, parent=root)
        root.destroy()
        return
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(text), str(title), 0x10 if error else 0x40)
    except Exception:
        print(f"{title}: {text}", file=sys.stderr)


def _ensure(dep: str, pip_name: str | None = None) -> None:
    if importlib.util.find_spec(dep) is not None:
        return
    subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name or dep])


def _xor(data: bytes, key: bytes, nonce: bytes) -> bytes:
    out = bytearray(len(data))
    off = 0
    ctr = 0
    while off < len(data):
        block = hashlib.blake2s(nonce + ctr.to_bytes(8, "little"), key=key, digest_size=32).digest()
        n = min(32, len(data) - off)
        for i in range(n):
            out[off + i] = data[off + i] ^ block[i]
        off += n
        ctr += 1
    return bytes(out)


def _install_runtime() -> None:
    """Load the editable runtime shipped in ./src.

    1.43 intentionally has no hidden older-runtime fallback: if the source folder
    is missing, startup fails instead of silently running an older build.
    """
    if not SOURCE_RUNTIME.is_dir():
        raise RuntimeError("The editable Trigger Studio runtime folder 'src' is missing from this release.")
    sys.path.insert(0, str(SOURCE_RUNTIME))


def main() -> int:
    try:
        _install_runtime()
        mode = sys.argv[1].lower() if len(sys.argv) > 1 else "gui"
        # Guard/manual/example modes do not need Pymem. Keeping them dependency
        # free lets Blank Map Guard arm a fresh install before Trigger Studio's
        # normal live-process package is installed.
        if mode in {"guard", "--blank-map-guard"}:
            import blank_map_guard
            sys.argv = [sys.argv[0]] + sys.argv[2:]
            return int(blank_map_guard.main())
        if mode == "manual":
            webbrowser.open((ROOT / "docs" / "FEATURES.html").as_uri())
            return 0
        if mode == "examples":
            webbrowser.open((ROOT / "docs" / "EXAMPLES.html").as_uri())
            return 0

        _ensure("pymem", "pymem>=1.13.1")
        if mode == "compat":
            import compatibility_scan
            return int(compatibility_scan.main())

        from trigger_studio import App
        App().mainloop()
        return 0
    except Exception as exc:
        details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        try:
            (ROOT / "last_startup_error.txt").write_text(details, encoding="utf-8")
        except Exception:
            pass
        _message("War2 Trigger Studio", f"Startup failed:\n\n{exc}\n\nDetails were written to last_startup_error.txt")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
