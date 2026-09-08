from __future__ import annotations
import json
import sys
from pathlib import Path

from compatibility import parse_loaded_pe, scan_compatibility


def main() -> int:
    try:
        import pymem
        import pymem.process
    except Exception as exc:
        print("Pymem is required:", exc)
        return 2
    pm = None
    try:
        pm = pymem.Pymem("Warcraft II.exe")
        module = pymem.process.module_from_name(pm.process_handle, "Warcraft II.exe")
        if not module:
            raise RuntimeError("Warcraft II.exe module was not found")
        base = int(module.lpBaseOfDll)
        info = scan_compatibility(pm, base, parse_loaded_pe(pm, base))
        print("Warcraft II Trigger Studio Universal Compatibility Report")
        print("=" * 58)
        print(json.dumps(info.to_dict(), indent=2))
        out = Path(__file__).resolve().parent.parent / "compatibility_last.json"
        out.write_text(json.dumps(info.to_dict(), indent=2) + "\n", encoding="utf-8")
        print(f"\nSaved: {out}")
        return 0
    except Exception as exc:
        print("COMPATIBILITY SCAN FAILED:", exc)
        return 1
    finally:
        if pm:
            try: pm.close_process()
            except Exception: pass

if __name__ == "__main__":
    raise SystemExit(main())
