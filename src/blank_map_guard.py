from __future__ import annotations

import argparse
import ctypes
import struct
import sys
import time
from ctypes import wintypes
from compatibility import resolve_victory_layout, KNOWN_BUILDS

PROCESS_NAME = "Warcraft II.exe"
EXPECTED_TIMESTAMP = 0x699E13E7
EXPECTED_IMAGE_SIZE = 0x0062B000
VICTORY_UPDATE_RVA = 0x000F4F60
MULTIPLAYER_GATE_RVA = 0x00522F5B
DEMO_MODE_RVA = 0x0051BCD4
CHEAT_BITS_RVA = 0x0051B270

TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PAGE_EXECUTE_READWRITE = 0x40
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform.startswith("win") else None
if kernel32 is not None:
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.Module32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel32.Module32FirstW.restype = wintypes.BOOL
    kernel32.Module32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel32.Module32NextW.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    kernel32.WriteProcessMemory.restype = wintypes.BOOL
    kernel32.VirtualProtectEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel32.VirtualProtectEx.restype = wintypes.BOOL
    kernel32.FlushInstructionCache.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t]
    kernel32.FlushInstructionCache.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD), ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_ubyte)), ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE), ("szModule", wintypes.WCHAR * 256), ("szExePath", wintypes.WCHAR * 260),
    ]


def winerr(msg: str):
    raise RuntimeError(f"{msg}: {ctypes.WinError(ctypes.get_last_error())}")


def find_pid(name: str) -> int | None:
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        winerr("CreateToolhelp32Snapshot(process)")
    try:
        entry = PROCESSENTRY32W(); entry.dwSize = ctypes.sizeof(entry)
        if not kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            return None
        while True:
            if entry.szExeFile.lower() == name.lower():
                return int(entry.th32ProcessID)
            if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                return None
    finally:
        kernel32.CloseHandle(snap)


def find_module_base(pid: int, name: str) -> int:
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap == INVALID_HANDLE_VALUE:
        winerr("CreateToolhelp32Snapshot(module)")
    try:
        entry = MODULEENTRY32W(); entry.dwSize = ctypes.sizeof(entry)
        if not kernel32.Module32FirstW(snap, ctypes.byref(entry)):
            winerr("Module32FirstW")
        fallback = 0
        while True:
            base = ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value or 0
            if not fallback:
                fallback = int(base)
            if entry.szModule.lower() == name.lower():
                return int(base)
            if not kernel32.Module32NextW(snap, ctypes.byref(entry)):
                break
        if fallback:
            return fallback
        raise RuntimeError("Warcraft module base not found")
    finally:
        kernel32.CloseHandle(snap)


def open_process(pid: int):
    access = PROCESS_QUERY_INFORMATION | PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE
    handle = kernel32.OpenProcess(access, False, pid)
    if not handle:
        winerr("OpenProcess")
    return handle


def read_mem(handle, address: int, size: int) -> bytes:
    buf = (ctypes.c_ubyte * size)()
    got = ctypes.c_size_t()
    if not kernel32.ReadProcessMemory(handle, ctypes.c_void_p(address), buf, size, ctypes.byref(got)):
        winerr(f"ReadProcessMemory 0x{address:08X}")
    if got.value != size:
        raise RuntimeError(f"Short read at 0x{address:08X}: {got.value}/{size}")
    return bytes(buf)


def write_code(handle, address: int, data: bytes) -> None:
    old = wintypes.DWORD()
    if not kernel32.VirtualProtectEx(handle, ctypes.c_void_p(address), len(data), PAGE_EXECUTE_READWRITE, ctypes.byref(old)):
        winerr("VirtualProtectEx")
    try:
        src = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        wrote = ctypes.c_size_t()
        if not kernel32.WriteProcessMemory(handle, ctypes.c_void_p(address), src, len(data), ctypes.byref(wrote)):
            winerr("WriteProcessMemory")
        if wrote.value != len(data):
            raise RuntimeError(f"Short write: {wrote.value}/{len(data)}")
        kernel32.FlushInstructionCache(handle, ctypes.c_void_p(address), len(data))
    finally:
        tmp = wintypes.DWORD()
        kernel32.VirtualProtectEx(handle, ctypes.c_void_p(address), len(data), old.value, ctypes.byref(tmp))
    if read_mem(handle, address, len(data)) != data:
        raise RuntimeError("Executable patch verification failed")


def pe_identity(handle, base: int) -> tuple[int, int]:
    head = read_mem(handle, base, 0x400)
    if head[:2] != b"MZ":
        raise RuntimeError("Warcraft module has no MZ header")
    pe = struct.unpack_from("<I", head, 0x3C)[0]
    if pe + 0x60 >= len(head):
        head = read_mem(handle, base, max(0x800, pe + 0x200))
    if head[pe:pe+4] != b"PE\0\0":
        raise RuntimeError("Warcraft module has no PE header")
    timestamp = struct.unpack_from("<I", head, pe + 8)[0]
    optional = pe + 24
    image_size = struct.unpack_from("<I", head, optional + 56)[0]
    return timestamp, image_size


class _HandlePM:
    def __init__(self, handle):
        self.handle = handle
    def read_bytes(self, address: int, size: int):
        return read_mem(self.handle, address, size)


def victory_layout(handle, base: int, image_size: int) -> dict:
    return resolve_victory_layout(_HandlePM(handle), base, image_size)


def patch_state(handle, base: int, image_size: int) -> str:
    layout = victory_layout(handle, base, image_size)
    expected = bytes(layout["signature"])
    address = int(layout["victory_update"])
    current = read_mem(handle, address, len(expected))
    if current == expected:
        return "Original"
    if current[:1] == b"\xC3" and current[1:] == expected[1:]:
        return "Armed"
    return "Unknown"


def arm(handle, base: int, image_size: int) -> str:
    layout = victory_layout(handle, base, image_size)
    state = patch_state(handle, base, image_size)
    if state == "Armed":
        return "already armed"
    if state != "Original":
        raise RuntimeError("victory_update bytes are already modified by another tool; refusing to patch")
    write_code(handle, int(layout["victory_update"]), b"\xC3")
    if patch_state(handle, base, image_size) != "Armed":
        raise RuntimeError("Blank Map Guard arm verification failed")
    return "armed"


def disarm(handle, base: int, image_size: int) -> str:
    layout = victory_layout(handle, base, image_size)
    state = patch_state(handle, base, image_size)
    if state == "Original":
        return "already native"
    if state != "Armed":
        raise RuntimeError("victory_update bytes are modified by another tool; refusing to overwrite")
    write_code(handle, int(layout["victory_update"]), b"\x80")
    if patch_state(handle, base, image_size) != "Original":
        raise RuntimeError("Blank Map Guard restore verification failed")
    return "restored"


def main() -> int:
    ap = argparse.ArgumentParser(description="Arm a signature-compatible Warcraft II Remastered x86 build for a truly empty trigger-driven map.")
    ap.add_argument("command", nargs="?", choices=("arm", "disarm", "status"), default="arm")
    ap.add_argument("--wait", action="store_true", help="Wait for Warcraft II.exe to start.")
    args = ap.parse_args()
    if not sys.platform.startswith("win"):
        print("Blank Map Guard runs on Windows only.")
        return 2

    pid = find_pid(PROCESS_NAME)
    while pid is None and args.wait:
        print("Waiting for Warcraft II.exe ...", flush=True)
        time.sleep(1.0)
        pid = find_pid(PROCESS_NAME)
    if pid is None:
        print("Warcraft II.exe is not running. Start it or use --wait.")
        return 1

    handle = open_process(pid)
    try:
        base = find_module_base(pid, PROCESS_NAME)
        timestamp, image = pe_identity(handle, base)
        label = KNOWN_BUILDS.get(timestamp, "unknown timestamp; using source-signature scan")
        print(f"PID {pid} | base 0x{base:08X} | timestamp 0x{timestamp:08X} | image 0x{image:X} | {label}")
        layout = victory_layout(handle, base, image)
        print(
            "Resolved victory_update RVA 0x%X | CheatBits RVA 0x%X | multiplayer RVA 0x%X" % (
                int(layout["victory_update"]) - base, int(layout["cheat_bits"]) - base, int(layout["multiplayer"]) - base
            )
        )
        if args.command == "status":
            print("Blank Map Guard state:", patch_state(handle, base, image))
        elif args.command == "arm":
            print("Blank Map Guard:", arm(handle, base, image))
            print("SAFE TO ENTER EMPTY MAP: stock victory_update is temporarily bypassed.")
            print("When Trigger Studio starts, put 'Blank Map Bootstrap' first; it sets CHEAT_NOVICTORY and restores this temporary code bridge.")
        else:
            print("Blank Map Guard:", disarm(handle, base, image))
        return 0
    except Exception as exc:
        print("ERROR:", exc)
        return 3
    finally:
        kernel32.CloseHandle(handle)


if __name__ == "__main__":
    raise SystemExit(main())
