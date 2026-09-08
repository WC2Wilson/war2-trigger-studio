from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import struct
from typing import Iterable

KNOWN_BUILDS = {
    0x6813B7ED: "Warcraft II Remastered 1.0.2.2505 (installed)",
    0x681446FD: "Warcraft II Remastered 1.0.2.2505 (alternate)",
    0x699E13E7: "Warcraft II Remastered 1.0.2.2818",
}

# Baseline RVAs are from the validated 1.0.2.2505/2818 x86 layout.  Unknown
# builds are not trusted merely because these numbers happen to be readable.
BASELINE = {
    "unit_run": 0x000EEA80,
    "damage_unit": 0x000BD8F0,
    "victory_update": 0x000F4F60,
    "max_units": 0x0051BFB8,
    "gp_units": 0x0051C704,
    "multiplayer": 0x00522F5B,
    "demo_mode": 0x0051BCD4,
    "cheat_bits": 0x0051B270,
}

# Pattern language: None = wildcard byte.  These are source-correlated anchors,
# not version strings.  They intentionally include structure offsets/branch
# shapes so an unrelated prologue cannot pass the scan.
UNIT_RUN_PATTERN: tuple[int | None, ...] = (
    0x55,0x8B,0xEC,0x51,0x53,0x8B,0x1D,
    None,None,None,None,
    0x56,0x8B,0x35,
    None,None,None,None,
    0x89,0x35,None,None,None,None,
    0x57,0x85,0xDB,
)
DAMAGE_PATTERN: tuple[int | None, ...] = (
    0x55,0x8B,0xEC,0x56,0x8B,0x75,0x0C,0x0F,0xB7,0x4E,0x1E,0xF6,0xC1,0x07,
)
VICTORY_PATTERN: tuple[int | None, ...] = (
    0x80,0x3D,None,None,None,None,0x00,0x75,0x15,
    0x80,0x3D,None,None,None,None,0x00,0x75,0x0C,
    0xF7,0x05,None,None,None,None,0x00,0x02,0x00,0x00,0x75,0x2D,
)

@dataclass
class BuildInfo:
    timestamp: int
    image_size: int
    machine: int
    optional_magic: int
    label: str = ""
    known: bool = False
    signature_compatible: bool = False
    data_delta: int = 0
    code_delta: int = 0
    anchors: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def mode(self) -> str:
        if self.known:
            return "Known / full validation"
        if self.signature_compatible:
            return "Universal signature compatibility"
        return "Unverified"

    def to_dict(self) -> dict:
        return {
            "timestamp": f"0x{self.timestamp:08X}",
            "image_size": f"0x{self.image_size:X}",
            "machine": f"0x{self.machine:04X}",
            "optional_magic": f"0x{self.optional_magic:04X}",
            "label": self.label,
            "known": self.known,
            "signature_compatible": self.signature_compatible,
            "data_delta": self.data_delta,
            "code_delta": self.code_delta,
            "anchors": {k: f"0x{v:X}" for k, v in self.anchors.items()},
            "notes": list(self.notes),
        }


def parse_loaded_pe(pm, base: int) -> BuildInfo:
    head = bytes(pm.read_bytes(base, 0x1000))
    if head[:2] != b"MZ":
        raise RuntimeError("Loaded Warcraft module has no MZ header")
    pe = struct.unpack_from("<I", head, 0x3C)[0]
    if pe + 0x80 > len(head):
        head = bytes(pm.read_bytes(base, max(0x2000, pe + 0x200)))
    if head[pe:pe+4] != b"PE\0\0":
        raise RuntimeError("Loaded Warcraft module has no PE header")
    machine = struct.unpack_from("<H", head, pe + 4)[0]
    timestamp = struct.unpack_from("<I", head, pe + 8)[0]
    optional = pe + 24
    optional_magic = struct.unpack_from("<H", head, optional)[0]
    image_size = struct.unpack_from("<I", head, optional + 56)[0]
    known = timestamp in KNOWN_BUILDS
    label = KNOWN_BUILDS.get(timestamp, f"Unknown Remastered build 0x{timestamp:08X}")
    return BuildInfo(timestamp, image_size, machine, optional_magic, label=label, known=known)


def find_masked(data: bytes, pattern: Iterable[int | None]) -> list[int]:
    pat = tuple(pattern)
    if not pat or len(data) < len(pat):
        return []
    # Pick the longest literal run as a fast seed, then verify wildcards.
    runs: list[tuple[int, bytes]] = []
    start = None
    buf = bytearray()
    for i, value in enumerate(pat + (None,)):
        if value is None:
            if start is not None and buf:
                runs.append((start, bytes(buf)))
            start = None
            buf.clear()
        else:
            if start is None:
                start = i
            buf.append(value)
    if not runs:
        return list(range(len(data) - len(pat) + 1))
    seed_off, seed = max(runs, key=lambda x: len(x[1]))
    hits: list[int] = []
    pos = 0
    while True:
        found = data.find(seed, pos)
        if found < 0:
            break
        candidate = found - seed_off
        if 0 <= candidate <= len(data) - len(pat):
            chunk = data[candidate:candidate+len(pat)]
            if all(v is None or chunk[i] == v for i, v in enumerate(pat)):
                hits.append(candidate)
        pos = found + 1
    return hits


def unique_masked(data: bytes, pattern: Iterable[int | None], label: str) -> int:
    hits = find_masked(data, pattern)
    if len(hits) != 1:
        raise RuntimeError(f"Universal compatibility scan for {label} found {len(hits)} candidates")
    return hits[0]


def _uniform_delta(pairs: list[tuple[int, int]], label: str) -> tuple[int | None, str]:
    if not pairs:
        return None, f"No {label} relocation anchors were available"
    deltas = [actual - expected for actual, expected in pairs]
    if len(set(deltas)) != 1:
        text = ", ".join(f"{actual:#x}-{expected:#x}={actual-expected:+#x}" for actual, expected in pairs)
        return None, f"{label} anchors do not share one relocation delta ({text})"
    return deltas[0], f"{label} relocation delta {deltas[0]:+#x} validated by {len(pairs)} independent anchors"


def scan_compatibility(pm, base: int, info: BuildInfo) -> BuildInfo:
    if info.machine != 0x014C or info.optional_magic != 0x010B:
        raise RuntimeError(
            f"Warcraft module is not the supported x86 PE32 architecture "
            f"(machine=0x{info.machine:04X}, optional=0x{info.optional_magic:04X})"
        )
    if not (0x00300000 <= info.image_size <= 0x02000000):
        raise RuntimeError(f"Implausible Warcraft SizeOfImage 0x{info.image_size:X}")

    image = bytes(pm.read_bytes(base, info.image_size))
    unit_run = unique_masked(image, UNIT_RUN_PATTERN, "unit_run")
    damage = unique_masked(image, DAMAGE_PATTERN, "damage_damage_unit")
    victory_hits = find_masked(image, VICTORY_PATTERN)
    if not victory_hits:
        victory_hits = find_masked(image, (0xC3,) + VICTORY_PATTERN[1:])
    if len(victory_hits) != 1:
        raise RuntimeError(f"Universal compatibility scan for victory_update found {len(victory_hits)} candidates")
    victory = victory_hits[0]

    # Decode absolute data operands from the two native-verified anchors.
    unit_chunk = image[unit_run:unit_run+len(UNIT_RUN_PATTERN)]
    max_units_va = struct.unpack_from("<I", unit_chunk, 7)[0]
    gp_units_va = struct.unpack_from("<I", unit_chunk, 14)[0]
    vic_chunk = image[victory:victory+len(VICTORY_PATTERN)]
    multiplayer_va = struct.unpack_from("<I", vic_chunk, 2)[0]
    demo_va = struct.unpack_from("<I", vic_chunk, 11)[0]
    cheat_va = struct.unpack_from("<I", vic_chunk, 20)[0]

    anchors = {
        "unit_run": unit_run,
        "damage_unit": damage,
        "victory_update": victory,
        "max_units": max_units_va - base,
        "gp_units": gp_units_va - base,
        "multiplayer": multiplayer_va - base,
        "demo_mode": demo_va - base,
        "cheat_bits": cheat_va - base,
    }
    info.anchors.update(anchors)

    data_delta, data_note = _uniform_delta([
        (anchors["max_units"], BASELINE["max_units"]),
        (anchors["gp_units"], BASELINE["gp_units"]),
        (anchors["multiplayer"], BASELINE["multiplayer"]),
        (anchors["demo_mode"], BASELINE["demo_mode"]),
        (anchors["cheat_bits"], BASELINE["cheat_bits"]),
    ], "data")
    code_delta, code_note = _uniform_delta([
        (anchors["unit_run"], BASELINE["unit_run"]),
        (anchors["damage_unit"], BASELINE["damage_unit"]),
        (anchors["victory_update"], BASELINE["victory_update"]),
    ], "code")
    info.notes.extend([data_note, code_note])

    # Known builds remain supported even when an antivirus/hotpatch changes a
    # nonessential anchor; unknown builds must prove a uniform source layout.
    if data_delta is None:
        if info.known:
            data_delta = 0
            info.notes.append("Known build: using validated baseline data layout despite relocation scan disagreement")
        else:
            raise RuntimeError(
                "Unknown Remastered build changed the data layout non-uniformly; universal mode refused to guess addresses. "
                + data_note
            )
    if code_delta is None:
        if info.known:
            code_delta = 0
            info.notes.append("Known build: using validated baseline code layout for fixed hook windows")
        else:
            # Most gameplay functions are individually signature-resolved, but the
            # simulation hook/vision patch windows require a coherent code shift.
            raise RuntimeError(
                "Unknown Remastered build changed the code layout non-uniformly; universal mode refused fixed hook patches. "
                + code_note
            )

    info.data_delta = int(data_delta)
    info.code_delta = int(code_delta)
    info.signature_compatible = True
    if not info.known:
        info.label = f"Signature-compatible Remastered x86 build 0x{info.timestamp:08X}"
        info.notes.append(
            "Unknown timestamp accepted because independent unit, damage, victory, and data-layout anchors all validated."
        )
    return info


def export_report(info: BuildInfo, path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(info.to_dict(), fh, indent=2)
        fh.write("\n")

def resolve_victory_layout(pm, base: int, image_size: int) -> dict[str, int | bytes]:
    """Locate source victory_update and decode its three absolute globals.

    Returns live addresses, not RVAs.  The scan accepts either the native first
    byte (0x80) or our one-byte pre-map RET bridge (0xC3), provided the remainder
    of the source-correlated signature is intact.
    """
    image = bytes(pm.read_bytes(base, image_size))
    hits = find_masked(image, VICTORY_PATTERN)
    # If armed, the first byte is RET instead of the pattern's 0x80.
    if not hits:
        armed = (0xC3,) + VICTORY_PATTERN[1:]
        hits = find_masked(image, armed)
    if len(hits) != 1:
        raise RuntimeError(f"victory_update universal scan found {len(hits)} candidates")
    rva = hits[0]
    chunk = image[rva:rva+len(VICTORY_PATTERN)]
    if chunk[0] == 0xC3:
        # Restore the semantic byte only for decoding; all operands remain live.
        chunk = b"\x80" + chunk[1:]
    return {
        "victory_update": base + rva,
        "victory_rva": rva,
        "multiplayer": struct.unpack_from("<I", chunk, 2)[0],
        "demo_mode": struct.unpack_from("<I", chunk, 11)[0],
        "cheat_bits": struct.unpack_from("<I", chunk, 20)[0],
        "signature": chunk,
    }
