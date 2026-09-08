from __future__ import annotations

import math
import random
import struct
import time
from typing import Any

from engine import ActionDeferred
from source_features_128 import (
    SourceFeature128Mixin,
    SF_HIDDEN,
    SF_COMPLETED,
    IS_FLYER,
    IS_TANKER,
    IS_TRANSPORT,
)
from ultimate_features import DEAD_FLAG_MASK


CAMPAIGN_OBJECTIVE_STATES = ("Active", "Completed", "Failed", "Hidden", "Missing")
CUTSCENE_STATES = ("Inactive", "Active")
SCENE_ACTOR_STATES = ("Alive", "Dead", "Hidden", "Removed", "Missing")

# Remastered native in-game Objectives bridge for 1.0.2.2818.
#
# 1.37 proved the native pause-menu path but crashed because Trigger Studio called
# Warcraft's internal C++ allocator directly from the simulation mailbox while
# constructing std::vector<std::string>. 1.38 does not call the game allocator at
# all. Instead it patches only the two call sites inside the validated Objectives
# renderer:
#   * provider call: preferred VA 0x005457EC -> stock provider 0x00545BB0
#   * vector destructor call: preferred VA 0x0054586F -> stock dtor 0x00527AF0
# When trigger override is active, the provider call-site stub returns a read-only
# vector view backed by a dedicated VirtualAllocEx block. The matching destructor
# call-site stub recognizes that exact vector and clears the local 3-pointer view
# without asking Warcraft to free Trigger Studio memory. Stock map/campaign
# objectives take the untouched original path whenever override mode is disabled.
#
# The actual native pause-menu opener is preferred VA 0x005437F0. It is called
# through the already-proven simulation-thread dispatcher with argument 2, exactly
# matching Warcraft's own pause/menu state transition rather than writing a mode
# variable and hoping the front end notices it.
NATIVE_OBJECTIVES_PROVIDER_RVA = 0x00145BB0
NATIVE_OBJECTIVES_PROVIDER_CALL_RVA = 0x001457EC
NATIVE_OBJECTIVES_PROVIDER_CALL_ORIGINAL = b"\xE8\xBF\x03\x00\x00"
NATIVE_OBJECTIVES_VECTOR_DTOR_RVA = 0x00127AF0
NATIVE_OBJECTIVES_DTOR_CALL_RVA = 0x0014586F
NATIVE_OBJECTIVES_DTOR_CALL_ORIGINAL = b"\xE8\x7C\x22\xFE\xFF"
NATIVE_OBJECTIVES_OPEN_RVA = 0x001437F0
NATIVE_OBJECTIVES_OPEN_SIGNATURE = b"\x55\x8B\xEC\xE8\x58\x5E\x0E\x00"
NATIVE_OBJECTIVES_PAUSE_MODE_RVA = 0x0055DFDC
NATIVE_OBJECTIVES_PAUSE_MODE = 2
NATIVE_OBJECTIVES_CONTROL_OFFSET = 0x1E00
NATIVE_OBJECTIVES_PROVIDER_STUB_OFFSET = 0x1E40
NATIVE_OBJECTIVES_DTOR_STUB_OFFSET = 0x1EA0
NATIVE_OBJECTIVES_HOOK_LIMIT = 0x1FC0
NATIVE_OBJECTIVES_DATA_SIZE = 0x10000
NATIVE_OBJECTIVES_TEXT_OFFSET = 0x1000
NATIVE_OBJECTIVES_MAX_LINES = 64
NATIVE_STRING_RECORD_SIZE = 24
NATIVE_STRING_SSO_CAPACITY = 15


class CampaignFeatureMixin(SourceFeature128Mixin):
    """Campaign/objective/cutscene layer, updated for Trigger Studio 1.38.

    Trigger-authored objective text now feeds the actual in-game pause-menu
    Objectives renderer shown while a match is running. 1.38 uses a renderer
    call-site view instead of transferring heap ownership, so no Warcraft C++
    allocator/free ABI is guessed or invoked by Trigger Studio.
    """

    # 1.0.2.2818 cell_set_pos writes the clamped top-left scroll pixels here.
    # These addresses are source-correlated and the camera callback itself is
    # already signature-validated by LiveAdapter before this mixin can run.
    CAMERA_X_RVA = 0x51AD80
    CAMERA_Y_RVA = 0x51AD84

    def _init_massive_features(self) -> None:
        super()._init_massive_features()
        self._campaign_objectives: dict[str, dict[str, Any]] = {
            str(name): {"text": str(text), "state": "Active", "order": index}
            for index, (name, text) in enumerate(dict(getattr(self, "objectives", {}) or {}).items())
        }
        self._campaign_objective_serial = len(self._campaign_objectives)
        self._campaign_hud_visible = False
        self._campaign_hud_recipients = "All active players"
        self._campaign_hud_color = "Yellow / gold — native normal"
        self._campaign_hud_refresh_seconds = 3.5
        self._campaign_hud_next = 0.0
        self._campaign_hud_pending_text: str | None = None
        self._campaign_briefing: dict[str, str] = {"title": "", "objectives": "", "story": ""}
        self._campaign_cutscene_active = False
        self._campaign_cutscene_label = ""
        self._campaign_saved_camera: tuple[int, int] | None = None
        self._campaign_camera_motion: dict[str, Any] | None = None
        self._campaign_camera_follow: dict[str, Any] | None = None
        self._campaign_camera_shake: dict[str, Any] | None = None
        self._campaign_camera_next = 0.0
        self._campaign_actor_status: dict[str, str] = {}
        self._campaign_actor_meta: dict[str, dict[str, Any]] = {}
        self._campaign_rescue_totals: dict[int, int] = {i: 0 for i in range(16)}
        self._campaign_capture_totals: dict[int, int] = {i: 0 for i in range(16)}
        self._campaign_rescue_goal: dict[int, int] = {}
        self._campaign_rng = random.Random(time.time_ns())
        self._campaign_scene_log: list[str] = []
        # Trigger-side objectives are an override layer. If the sidecar already
        # authored objectives they win immediately; otherwise the PUD/campaign's
        # own objectives remain untouched until a trigger creates/changes one.
        self._campaign_objective_override_active = bool(self._campaign_objectives)
        self._native_objectives_hook_installed = False
        self._native_objectives_provider_call_address = 0
        self._native_objectives_dtor_call_address = 0
        self._native_objectives_provider_stub_address = 0
        self._native_objectives_dtor_stub_address = 0
        self._native_objectives_control_address = 0
        self._native_objectives_data_address = 0
        self._native_objectives_data_size = 0
        self._native_objectives_pending_signature: tuple[str, ...] | None = None
        self._native_objectives_rearm_next = 0.0
        self._native_objectives_rearm_error = ""

    def _massive_begin_run(self) -> None:
        super()._massive_begin_run()
        # Keep authored objectives, but reset runtime state exactly like starting a
        # fresh campaign mission.
        for record in self._campaign_objectives.values():
            record["state"] = "Active"
        self._campaign_objective_override_active = bool(self._campaign_objectives)
        self._campaign_hud_visible = False
        self._campaign_hud_next = 0.0
        self._campaign_hud_pending_text = None
        self._campaign_cutscene_active = False
        self._campaign_cutscene_label = ""
        self._campaign_saved_camera = None
        self._campaign_camera_motion = None
        self._campaign_camera_follow = None
        self._campaign_camera_shake = None
        self._campaign_camera_next = 0.0
        self._campaign_actor_status.clear()
        self._campaign_actor_meta.clear()
        self._campaign_rescue_totals = {i: 0 for i in range(16)}
        self._campaign_capture_totals = {i: 0 for i in range(16)}
        self._campaign_scene_log.clear()
        self._native_objectives_pending_signature = None
        self._native_objectives_rearm_next = 0.0
        self._native_objectives_rearm_error = ""

    # ------------------------------------------------------------------ helpers
    def _native_objectives_addresses(self) -> dict[str, int]:
        info = getattr(self, "build_info", None)
        code_delta = int(getattr(info, "code_delta", 0) if info else 0)
        data_delta = int(getattr(info, "data_delta", 0) if info else 0)
        return {
            "provider": int(self.base) + NATIVE_OBJECTIVES_PROVIDER_RVA + code_delta,
            "provider_call": int(self.base) + NATIVE_OBJECTIVES_PROVIDER_CALL_RVA + code_delta,
            "vector_dtor": int(self.base) + NATIVE_OBJECTIVES_VECTOR_DTOR_RVA + code_delta,
            "dtor_call": int(self.base) + NATIVE_OBJECTIVES_DTOR_CALL_RVA + code_delta,
            "open": int(self.base) + NATIVE_OBJECTIVES_OPEN_RVA + code_delta,
            "pause_mode": int(self.base) + NATIVE_OBJECTIVES_PAUSE_MODE_RVA + data_delta,
        }

    def _native_objectives_supported(self) -> bool:
        if not getattr(self, "pm", None) or not getattr(self, "base", 0):
            return False
        if not getattr(self, "dispatcher_installed", False) or not getattr(self, "dispatcher_memory", 0):
            return False
        try:
            addresses = self._native_objectives_addresses()
            provider_call = bytes(self.pm.read_bytes(addresses["provider_call"], 5))
            dtor_call = bytes(self.pm.read_bytes(addresses["dtor_call"], 5))
            open_head = bytes(self.pm.read_bytes(addresses["open"], len(NATIVE_OBJECTIVES_OPEN_SIGNATURE)))
            if open_head != NATIVE_OBJECTIVES_OPEN_SIGNATURE:
                return False
            provider_ok = provider_call == NATIVE_OBJECTIVES_PROVIDER_CALL_ORIGINAL
            dtor_ok = dtor_call == NATIVE_OBJECTIVES_DTOR_CALL_ORIGINAL
            if self._native_objectives_hook_installed:
                if provider_call[:1] == b"\xE8" and self._native_objectives_provider_stub_address:
                    target = addresses["provider_call"] + 5 + struct.unpack("<i", provider_call[1:5])[0]
                    provider_ok = target == int(self._native_objectives_provider_stub_address)
                if dtor_call[:1] == b"\xE8" and self._native_objectives_dtor_stub_address:
                    target = addresses["dtor_call"] + 5 + struct.unpack("<i", dtor_call[1:5])[0]
                    dtor_ok = target == int(self._native_objectives_dtor_stub_address)
            return bool(provider_ok and dtor_ok)
        except Exception:
            return False

    def _native_objectives_remote_alloc(self) -> int:
        if self._native_objectives_data_address:
            return int(self._native_objectives_data_address)
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.VirtualAllocEx.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
            wintypes.DWORD, wintypes.DWORD,
        ]
        kernel32.VirtualAllocEx.restype = ctypes.c_void_p
        address = kernel32.VirtualAllocEx(
            wintypes.HANDLE(self.pm.process_handle), None,
            NATIVE_OBJECTIVES_DATA_SIZE, 0x3000, 0x04,
        )
        value = int(address or 0)
        if not value:
            raise ctypes.WinError(ctypes.get_last_error())
        self.pm.write_bytes(value, b"\x00" * NATIVE_OBJECTIVES_DATA_SIZE, NATIVE_OBJECTIVES_DATA_SIZE)
        self._native_objectives_data_address = value
        self._native_objectives_data_size = NATIVE_OBJECTIVES_DATA_SIZE
        return value

    def _native_objectives_remote_free(self) -> None:
        address = int(getattr(self, "_native_objectives_data_address", 0) or 0)
        if not address or not getattr(self, "pm", None):
            self._native_objectives_data_address = 0
            self._native_objectives_data_size = 0
            return
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.VirtualFreeEx.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD,
        ]
        kernel32.VirtualFreeEx.restype = wintypes.BOOL
        kernel32.VirtualFreeEx(
            wintypes.HANDLE(self.pm.process_handle), ctypes.c_void_p(address), 0, 0x8000
        )
        self._native_objectives_data_address = 0
        self._native_objectives_data_size = 0

    def _native_objectives_provider_stub(self, addresses: dict[str, int]) -> bytes:
        control = int(self.dispatcher_memory) + NATIVE_OBJECTIVES_CONTROL_OFFSET
        active = control
        begin = control + 4
        end = control + 8
        cap = control + 12
        code_addr = int(self.dispatcher_memory) + NATIVE_OBJECTIVES_PROVIDER_STUB_OFFSET
        code = bytearray()
        code += b"\xA1" + struct.pack("<I", active)                 # mov eax,[active]
        code += b"\x85\xC0"                                        # test eax,eax
        inactive_jz = len(code)
        code += b"\x0F\x84\x00\x00\x00\x00"                    # jz stock
        code += b"\x8B\x4C\x24\x04"                              # mov ecx,[esp+4] (out vector)
        code += b"\xA1" + struct.pack("<I", begin)                 # mov eax,[begin]
        code += b"\x85\xC0"
        empty_jz = len(code)
        code += b"\x0F\x84\x00\x00\x00\x00"
        code += b"\x89\x01"                                        # mov [ecx],eax
        code += b"\xA1" + struct.pack("<I", end)
        code += b"\x89\x41\x04"
        code += b"\xA1" + struct.pack("<I", cap)
        code += b"\x89\x41\x08"
        code += b"\x8B\xC1\xC3"                                  # mov eax,ecx ; ret
        stock = len(code)
        struct.pack_into("<i", code, inactive_jz + 2, stock - (inactive_jz + 6))
        struct.pack_into("<i", code, empty_jz + 2, stock - (empty_jz + 6))
        jmp_at = code_addr + len(code)
        code += b"\xE9" + self._relative32(jmp_at + 5, addresses["provider"])
        return bytes(code)

    def _native_objectives_dtor_stub(self, addresses: dict[str, int]) -> bytes:
        control = int(self.dispatcher_memory) + NATIVE_OBJECTIVES_CONTROL_OFFSET
        begin = control + 4
        code_addr = int(self.dispatcher_memory) + NATIVE_OBJECTIVES_DTOR_STUB_OFFSET
        code = bytearray()
        code += b"\x8B\x01"                                        # mov eax,[ecx]
        code += b"\x3B\x05" + struct.pack("<I", begin)             # cmp eax,[trigger begin]
        jne_pos = len(code)
        code += b"\x0F\x85\x00\x00\x00\x00"                    # jne stock dtor
        code += b"\xC7\x01\x00\x00\x00\x00"                    # clear local vector view
        code += b"\xC7\x41\x04\x00\x00\x00\x00"
        code += b"\xC7\x41\x08\x00\x00\x00\x00"
        code += b"\xC3"
        stock = len(code)
        struct.pack_into("<i", code, jne_pos + 2, stock - (jne_pos + 6))
        jmp_at = code_addr + len(code)
        code += b"\xE9" + self._relative32(jmp_at + 5, addresses["vector_dtor"])
        return bytes(code)

    def _ensure_native_objectives_hook(self) -> None:
        if self._native_objectives_hook_installed:
            return
        if not getattr(self, "dispatcher_installed", False) or not getattr(self, "dispatcher_memory", 0):
            raise RuntimeError("Native Objectives requires the simulation dispatcher")
        addresses = self._native_objectives_addresses()
        provider_call = bytes(self.pm.read_bytes(addresses["provider_call"], 5))
        dtor_call = bytes(self.pm.read_bytes(addresses["dtor_call"], 5))
        open_head = bytes(self.pm.read_bytes(addresses["open"], len(NATIVE_OBJECTIVES_OPEN_SIGNATURE)))
        if provider_call != NATIVE_OBJECTIVES_PROVIDER_CALL_ORIGINAL:
            raise RuntimeError("Native Objectives provider call site is modified; fully restart Warcraft before attaching")
        if dtor_call != NATIVE_OBJECTIVES_DTOR_CALL_ORIGINAL:
            raise RuntimeError("Native Objectives destructor call site is modified; fully restart Warcraft before attaching")
        if open_head != NATIVE_OBJECTIVES_OPEN_SIGNATURE:
            raise RuntimeError("Native Objectives pause-menu opener no longer matches the validated Remastered layout")

        # Never patch while the Objectives renderer itself may be executing.
        # State 2 is the native in-game Objectives submenu. Closing it returns the
        # pause-menu state to another value/zero and makes these two call sites idle.
        try:
            pause_state = int(self.pm.read_uint(addresses["pause_mode"]))
        except Exception:
            pause_state = 0
        if pause_state == NATIVE_OBJECTIVES_PAUSE_MODE:
            raise RuntimeError("Close Warcraft's Objectives screen before enabling the trigger objective bridge")

        self._native_objectives_remote_alloc()
        control = int(self.dispatcher_memory) + NATIVE_OBJECTIVES_CONTROL_OFFSET
        provider_stub_addr = int(self.dispatcher_memory) + NATIVE_OBJECTIVES_PROVIDER_STUB_OFFSET
        dtor_stub_addr = int(self.dispatcher_memory) + NATIVE_OBJECTIVES_DTOR_STUB_OFFSET
        provider_code = self._native_objectives_provider_stub(addresses)
        dtor_code = self._native_objectives_dtor_stub(addresses)
        if provider_stub_addr + len(provider_code) >= dtor_stub_addr:
            raise RuntimeError("Native Objectives provider stub overlaps destructor stub")
        if dtor_stub_addr + len(dtor_code) > int(self.dispatcher_memory) + NATIVE_OBJECTIVES_HOOK_LIMIT:
            raise RuntimeError("Native Objectives bridge exceeds reserved executable storage")

        self.pm.write_bytes(control, b"\x00" * 0x20, 0x20)
        self.pm.write_bytes(provider_stub_addr, provider_code, len(provider_code))
        self.pm.write_bytes(dtor_stub_addr, dtor_code, len(dtor_code))
        self._flush_dispatch_code(provider_stub_addr, len(provider_code))
        self._flush_dispatch_code(dtor_stub_addr, len(dtor_code))
        provider_patch = b"\xE8" + self._relative32(addresses["provider_call"] + 5, provider_stub_addr)
        dtor_patch = b"\xE8" + self._relative32(addresses["dtor_call"] + 5, dtor_stub_addr)
        # Install the destructor guard FIRST. With only that half installed, stock
        # objectives still use the stock provider and the guard simply tail-jumps
        # to the original destructor. Installing the provider first would create a
        # tiny race where Warcraft could receive our static vector and then send it
        # to its stock heap destructor.
        self._write_executable_bytes(addresses["dtor_call"], dtor_patch)
        try:
            self._write_executable_bytes(addresses["provider_call"], provider_patch)
        except Exception:
            self._write_executable_bytes(addresses["dtor_call"], NATIVE_OBJECTIVES_DTOR_CALL_ORIGINAL)
            self._native_objectives_remote_free()
            raise

        self._native_objectives_provider_call_address = addresses["provider_call"]
        self._native_objectives_dtor_call_address = addresses["dtor_call"]
        self._native_objectives_provider_stub_address = provider_stub_addr
        self._native_objectives_dtor_stub_address = dtor_stub_addr
        self._native_objectives_control_address = control
        self._native_objectives_hook_installed = True
        self.log("NATIVE OBJECTIVES READY: allocator-free in-game Objectives renderer bridge installed")

    def _free_pending_native_objectives(self) -> None:
        # Compatibility name retained for old action code. 1.38 never gives our
        # memory to Warcraft, so there is nothing native to free; this only turns
        # off the provider override atomically.
        control = int(getattr(self, "_native_objectives_control_address", 0) or 0)
        if control and getattr(self, "pm", None):
            try:
                self.pm.write_uint(control, 0)
            except Exception:
                pass
        self._native_objectives_pending_signature = None

    def _native_objective_lines(self) -> list[str]:
        visible = sorted(
            (record for record in self._campaign_objectives.values() if record.get("state") != "Hidden"),
            key=lambda record: int(record.get("order", 0)),
        )
        lines: list[str] = []
        for record in visible:
            state = str(record.get("state", "Active"))
            text = str(record.get("text", "")).strip()
            if not text:
                continue
            if state == "Completed":
                text = text + "  [Completed]"
            elif state == "Failed":
                text = text + "  [Failed]"
            if not text.startswith("-"):
                text = "-" + text
            lines.append(text)
        return lines or ["-No current objectives"]

    def _stage_native_objectives(self) -> bool:
        if not self._campaign_objective_override_active:
            return False
        self._ensure_native_objectives_hook()
        lines = self._native_objective_lines()[:NATIVE_OBJECTIVES_MAX_LINES]
        signature = tuple(lines)
        control = int(self._native_objectives_control_address)
        data = int(self._native_objectives_data_address)
        if not control or not data:
            raise RuntimeError("Native Objectives bridge storage is unavailable")
        try:
            if self._native_objectives_pending_signature == signature and int(self.pm.read_uint(control)) == 1:
                return True
        except Exception:
            pass

        # Do not rewrite backing std::string records while Warcraft is actively
        # drawing the Objectives submenu. A frame that already received our vector
        # keeps raw pointers into this block. Deferring the update until the screen
        # closes guarantees those pointers stay immutable for the full render call.
        try:
            if int(self.pm.read_uint(self._native_objectives_addresses()["pause_mode"])) == NATIVE_OBJECTIVES_PAUSE_MODE:
                raise ActionDeferred("Waiting for the native Objectives screen to close before refreshing objective text", retry_after=0.10)
        except ActionDeferred:
            raise
        except Exception:
            pass

        # Disable the call-site view while rewriting so the renderer can only see
        # either the complete old vector or normal map objectives, never a partial
        # record set.
        self.pm.write_uint(control, 0)
        records = bytearray(len(lines) * NATIVE_STRING_RECORD_SIZE)
        text_cursor = NATIVE_OBJECTIVES_TEXT_OFFSET
        for index, line in enumerate(lines):
            raw = line.encode("utf-8", errors="replace")
            if len(raw) > 2047:
                raw = raw[:2047]
            off = index * NATIVE_STRING_RECORD_SIZE
            if len(raw) <= NATIVE_STRING_SSO_CAPACITY:
                records[off:off + len(raw)] = raw
                records[off + len(raw)] = 0
                struct.pack_into("<I", records, off + 0x10, len(raw))
                struct.pack_into("<I", records, off + 0x14, NATIVE_STRING_SSO_CAPACITY)
            else:
                needed = len(raw) + 1
                if text_cursor + needed > NATIVE_OBJECTIVES_DATA_SIZE:
                    raise RuntimeError("Native objective text exceeds the reserved renderer buffer")
                ptr = data + text_cursor
                self.pm.write_bytes(ptr, raw + b"\x00", needed)
                struct.pack_into("<I", records, off, ptr)
                struct.pack_into("<I", records, off + 0x10, len(raw))
                struct.pack_into("<I", records, off + 0x14, len(raw))
                text_cursor += needed

        if records:
            self.pm.write_bytes(data, bytes(records), len(records))
        begin = data
        end = data + len(records)
        self.pm.write_uint(control + 4, begin)
        self.pm.write_uint(control + 8, end)
        self.pm.write_uint(control + 12, end)
        self.pm.write_uint(control, 1)
        self._native_objectives_pending_signature = signature
        self.log(f"NATIVE OBJECTIVES STAGED: {len(lines)} allocator-free Warcraft objective line(s)")
        return True

    def _request_native_objectives_screen(self) -> None:
        addresses = self._native_objectives_addresses()
        mode = self._read_game_mode()
        if mode != 3:
            raise RuntimeError(f"Native Objectives can only open while Warcraft is in Running mode 3 (current {mode})")
        # 0x5437F0 is Warcraft's own pause/menu opener. The game itself calls it
        # for front-end transitions; argument 2 selects the Objectives submenu.
        # Dispatching this native helper on Warcraft's main simulation thread is
        # the same route as the game, unlike 1.37's raw state write.
        self._call_cdecl(addresses["open"], [NATIVE_OBJECTIVES_PAUSE_MODE])
        self.log("NATIVE OBJECTIVES OPEN REQUESTED: native pause-menu opener state 2")

    def _open_native_objectives(self) -> bool:
        if self._campaign_objective_override_active:
            self._stage_native_objectives()
        else:
            self._free_pending_native_objectives()
        state = self._cached_action_value("native_objectives_open", lambda: {"requested": False})
        if not state["requested"]:
            self._request_native_objectives_screen()
            state["requested"] = True
        return True

    def _restore_native_objectives_hook(self) -> None:
        if not getattr(self, "pm", None):
            return
        # Stop publishing first. Keep the destructor guard alive for several game
        # frames so any renderer invocation already holding our static view can
        # finish without trying to free Trigger Studio memory.
        try:
            self._free_pending_native_objectives()
            time.sleep(0.08)
        except Exception:
            pass
        if self._native_objectives_hook_installed:
            try:
                provider = int(self._native_objectives_provider_call_address)
                dtor = int(self._native_objectives_dtor_call_address)
                if provider:
                    current = bytes(self.pm.read_bytes(provider, 5))
                    if current[:1] == b"\xE8":
                        target = provider + 5 + struct.unpack("<i", current[1:5])[0]
                        if target == int(self._native_objectives_provider_stub_address):
                            # Restore the provider FIRST so no new render invocation
                            # can acquire our static view. Keep the destructor guard
                            # alive for a few frames for any invocation already in flight.
                            self._write_executable_bytes(provider, NATIVE_OBJECTIVES_PROVIDER_CALL_ORIGINAL)
                            time.sleep(0.08)
                if dtor:
                    current = bytes(self.pm.read_bytes(dtor, 5))
                    if current[:1] == b"\xE8":
                        target = dtor + 5 + struct.unpack("<i", current[1:5])[0]
                        if target == int(self._native_objectives_dtor_stub_address):
                            self._write_executable_bytes(dtor, NATIVE_OBJECTIVES_DTOR_CALL_ORIGINAL)
            finally:
                self._native_objectives_hook_installed = False
                self._native_objectives_provider_call_address = 0
                self._native_objectives_dtor_call_address = 0
                self._native_objectives_provider_stub_address = 0
                self._native_objectives_dtor_stub_address = 0
                self._native_objectives_control_address = 0
                self._native_objectives_pending_signature = None
        try:
            self._native_objectives_remote_free()
        except Exception as exc:
            self.log(f"Native objectives data cleanup deferred: {exc}")

    def _campaign_point(self, args: dict[str, Any], *, key: str = "destination", xkey: str = "x", ykey: str = "y") -> tuple[int, int]:
        location_name = str(args.get(key, args.get("location", "Anywhere")))
        if location_name and location_name != "Anywhere":
            loc = self._find_location(location_name)
            return ((int(loc.left) + int(loc.right)) // 2, (int(loc.top) + int(loc.bottom)) // 2)
        return (int(args.get(xkey, 0)), int(args.get(ykey, 0)))

    def _campaign_current_camera(self) -> tuple[int, int] | None:
        if not getattr(self, "pm", None) or not getattr(self, "base", 0):
            return None
        try:
            px = int(self.pm.read_int(self.base + self.CAMERA_X_RVA))
            py = int(self.pm.read_int(self.base + self.CAMERA_Y_RVA))
            return (max(0, px >> 5), max(0, py >> 5))
        except Exception:
            return None

    def _campaign_camera_call(self, x: int, y: int) -> None:
        x = max(0, min(int(self.map_width) - 1, int(x)))
        y = max(0, min(int(self.map_height) - 1, int(y)))
        self._call_cdecl(self.spell_path["vision_set_pos"], [x, y])

    def _campaign_actor(self, name: Any, *, required: bool = True) -> Any | None:
        key = str(name or "Actor").strip()
        unit = self._resolve_unit_reference(key)
        if unit is None and required:
            raise RuntimeError(f"Scene actor {key!r} is missing or dead")
        return unit

    def _campaign_register_actor(self, name: str, unit: Any | None, *, created: bool = False) -> None:
        name = str(name).strip()
        if not name:
            raise ValueError("Scene actor name cannot be blank")
        self._save_reference(name, unit)
        if unit is None:
            self._campaign_actor_status[name] = "Missing"
            return
        self._campaign_actor_status[name] = "Hidden" if (int(unit.sflags) & SF_HIDDEN) else "Alive"
        self._campaign_actor_meta[name] = {
            "owner": int(unit.owner), "unit_type": int(unit.unit_type), "created": bool(created),
            "address": int(unit.address), "last_x": int(unit.x), "last_y": int(unit.y),
        }

    def _campaign_actor_state(self, name: str) -> str:
        unit = self._resolve_unit_reference(name)
        known = self._campaign_actor_status.get(name)
        if unit is not None:
            state = "Hidden" if int(unit.sflags) & SF_HIDDEN else "Alive"
            self._campaign_actor_status[name] = state
            return state
        if known in {"Dead", "Removed"}:
            return known
        return "Missing"

    def _campaign_objective(self, name: str, *, create: bool = False, text: str | None = None) -> dict[str, Any] | None:
        key = str(name).strip()
        if not key:
            raise ValueError("Campaign objective name cannot be blank")
        record = self._campaign_objectives.get(key)
        if record is None and create:
            record = {"text": text if text is not None else key, "state": "Active", "order": self._campaign_objective_serial}
            self._campaign_objective_serial += 1
            self._campaign_objectives[key] = record
        elif record is not None and text is not None:
            record["text"] = str(text)
        return record

    def _campaign_objective_text(self) -> str:
        visible = sorted(
            ((name, record) for name, record in self._campaign_objectives.items() if record.get("state") != "Hidden"),
            key=lambda item: int(item[1].get("order", 0)),
        )
        if not visible:
            return "OBJECTIVES: none"
        lines = ["SCENARIO OBJECTIVES"]
        prefix = {"Active": "[ ]", "Completed": "[X]", "Failed": "[!]", "Hidden": "[-]"}
        for _, record in visible:
            lines.append(f"{prefix.get(str(record.get('state')), '[ ]')} {record.get('text', '')}")
        return "\n".join(lines)

    def _campaign_publish_hud(self, text: str, player: int = 0) -> None:
        # Native-safe in-game text path. This intentionally does not call the
        # unverified modern C++ front-end objective widget.
        self._game_message({
            "text": text,
            "recipients": self._campaign_hud_recipients,
            "color": self._campaign_hud_color,
            "seconds": max(2, int(math.ceil(self._campaign_hud_refresh_seconds + 0.75))),
            "also_log": False,
        }, player)

    def _campaign_timed_message(self, cache_name: str, text: str, seconds: float, player: int, *, color: str = "White — native highlight", recipients: str = "All active players") -> bool:
        state = self._cached_action_value(cache_name, lambda: {"started": time.monotonic(), "published": False})
        if not state["published"]:
            self._game_message({"text": text, "color": color, "recipients": recipients, "seconds": max(1, int(math.ceil(seconds))), "also_log": True}, player)
            state["published"] = True
        if time.monotonic() - float(state["started"]) < max(0.0, float(seconds)):
            raise ActionDeferred(f"{cache_name} still displaying", retry_after=0.10)
        return True

    def _campaign_non_auxiliary_mobile_count(self, owner: int) -> int:
        total = 0
        for unit in self.units():
            if int(unit.owner) != int(owner) or int(unit.sflags) & DEAD_FLAG_MASK:
                continue
            if int(unit.unit_type) >= 58:
                continue
            flags = int(self._source128_flags(int(unit.unit_type)))
            # reference module slot_alive / genocide deliberately exclude tankers,
            # transports and flyers from the men count.
            if flags & (IS_TANKER | IS_TRANSPORT | IS_FLYER):
                continue
            total += 1
        return total

    def _campaign_building_count(self, owner: int) -> int:
        return sum(1 for unit in self.units() if int(unit.owner) == int(owner) and int(unit.unit_type) >= 58 and not (int(unit.sflags) & DEAD_FLAG_MASK))

    # --------------------------------------------------------------- maintenance
    def _massive_prepare_pre(self, world: list[Any]) -> bool:
        result = super()._massive_prepare_pre(world)
        if result is False:
            return False
        now = time.monotonic()

        # Smooth camera motion is advanced outside an action context so each
        # changing camera coordinate gets its own mailbox command. The current
        # step is retained until the exact queued signature is consumed.
        motion = self._campaign_camera_motion
        if motion is not None and now >= float(motion.get("next", 0.0)):
            steps = max(1, int(motion["steps"]))
            index = min(steps, int(motion["index"]) + 1)
            t = index / steps
            # Smoothstep avoids the hard constant-speed robotic pan.
            smooth = t * t * (3.0 - 2.0 * t)
            x = round(float(motion["sx"]) + (float(motion["tx"]) - float(motion["sx"])) * smooth)
            y = round(float(motion["sy"]) + (float(motion["ty"]) - float(motion["sy"])) * smooth)
            try:
                self._campaign_camera_call(x, y)
            except ActionDeferred:
                motion["next"] = now + 0.05
                return False
            motion["index"] = index
            motion["next"] = now + float(motion["step_seconds"])
            if index >= steps:
                motion["done"] = True
                self._campaign_camera_motion = None

        shake = self._campaign_camera_shake
        if shake is not None and self._campaign_camera_motion is None and now >= float(shake.get("next", 0.0)):
            elapsed = now - float(shake["started"])
            if elapsed >= float(shake["duration"]):
                point = tuple(shake.get("pending") or shake["base"])
                try:
                    self._campaign_camera_call(*point)
                except ActionDeferred:
                    shake["pending"] = point
                    return False
                shake["pending"] = None
                self._campaign_camera_shake = None
            else:
                point = tuple(shake.get("pending") or (
                    int(shake["base"][0]) + self._campaign_rng.randint(-int(shake["magnitude"]), int(shake["magnitude"])),
                    int(shake["base"][1]) + self._campaign_rng.randint(-int(shake["magnitude"]), int(shake["magnitude"])),
                ))
                try:
                    self._campaign_camera_call(*point)
                except ActionDeferred:
                    shake["pending"] = point
                    return False
                shake["pending"] = None
                shake["next"] = now + 0.10

        follow = self._campaign_camera_follow
        if follow is not None and self._campaign_camera_motion is None and self._campaign_camera_shake is None and now >= self._campaign_camera_next:
            actor = self._resolve_unit_reference(follow.get("actor", ""))
            if actor is None:
                self._campaign_camera_follow = None
            else:
                point = tuple(follow.get("pending") or (int(actor.x), int(actor.y)))
                if point != tuple(follow.get("last", (-999, -999))):
                    try:
                        self._campaign_camera_call(*point)
                    except ActionDeferred:
                        follow["pending"] = point
                        return False
                    follow["pending"] = None
                    follow["last"] = point
                self._campaign_camera_next = now + max(0.10, float(follow.get("cadence", 0.20)))

        # Keep the allocator-free renderer view current whenever override mode is
        # active. The view is persistent, so manual Menu -> Objectives opens keep
        # using trigger text without rebuilding or transferring heap ownership.
        if self._campaign_objective_override_active and now >= self._native_objectives_rearm_next:
            if getattr(self, "dispatcher_installed", False) and getattr(self, "dispatcher_memory", 0):
                try:
                    self._stage_native_objectives()
                    self._native_objectives_rearm_error = ""
                    self._native_objectives_rearm_next = now + 0.25
                except ActionDeferred:
                    return False
                except Exception as exc:
                    message = str(exc)
                    if message != self._native_objectives_rearm_error:
                        self.log(f"Native objectives auto-stage unavailable: {message}")
                        self._native_objectives_rearm_error = message
                    self._native_objectives_rearm_next = now + 3.0

        if self._campaign_hud_visible and not self._campaign_cutscene_active and now >= self._campaign_hud_next:
            # 1.37 never refreshes objectives through map_msg/PM_STRING. The HUD
            # flag now means keep the native override armed; drawing remains 100%
            # Warcraft-owned through the real Objectives screen.
            self._campaign_hud_next = now + max(2.0, self._campaign_hud_refresh_seconds)
        return True

    def _massive_prepare_events(self, current: dict[tuple[int, int], Any], previous: dict[tuple[int, int], Any]) -> None:
        super()._massive_prepare_events(current, previous)

        # Generic ownership changes become useful campaign capture statistics.
        for key, unit in current.items():
            before = previous.get(key)
            if before is not None and int(before.owner) != int(unit.owner):
                self._campaign_capture_totals[int(unit.owner)] = self._campaign_capture_totals.get(int(unit.owner), 0) + 1

        # Source 1.28 rescue checks publish old live keys for the cycle in which
        # Give Units completes. Convert those edge events into cumulative totals.
        for key in getattr(self, "_source128_rescued_recent", set()):
            unit = current.get(key)
            if unit is not None:
                self._campaign_rescue_totals[int(unit.owner)] = self._campaign_rescue_totals.get(int(unit.owner), 0) + 1

        # Keep named actors generation-safe. If the reference no longer resolves,
        # use the engine's died/removed edge lists to distinguish scene outcomes.
        died_addresses = {int(unit.address) for unit in getattr(self, "died_units", [])}
        removed_addresses = {int(unit.address) for unit in getattr(self, "removed_units", [])}
        for name, meta in list(self._campaign_actor_meta.items()):
            unit = self._resolve_unit_reference(name)
            if unit is not None:
                meta["address"] = int(unit.address); meta["last_x"] = int(unit.x); meta["last_y"] = int(unit.y)
                self._campaign_actor_status[name] = "Hidden" if int(unit.sflags) & SF_HIDDEN else "Alive"
                continue
            address = int(meta.get("address", 0))
            if address in removed_addresses:
                self._campaign_actor_status[name] = "Removed"
            elif address in died_addresses or self._campaign_actor_status.get(name) == "Dead":
                self._campaign_actor_status[name] = "Dead"
            elif self._campaign_actor_status.get(name) not in {"Removed", "Dead"}:
                self._campaign_actor_status[name] = "Missing"

    # ---------------------------------------------------------------- conditions
    def massive_value(self, kind: str, args: dict[str, Any], player: int) -> Any:
        if kind == "Campaign Objective State":
            record = self._campaign_objective(str(args.get("name", "Objective 1")))
            return "Missing" if record is None else str(record.get("state", "Active"))
        if kind == "Cutscene State":
            return "Active" if self._campaign_cutscene_active else "Inactive"
        if kind == "Scene Actor State":
            return self._campaign_actor_state(str(args.get("actor", "Actor")))
        if kind == "Scene Actor At Location":
            actor = self._resolve_unit_reference(str(args.get("actor", "Actor")))
            if actor is None:
                return 0
            x, y = self._campaign_point(args, key="location")
            radius = max(0, int(args.get("radius", 0)))
            return int(max(abs(int(actor.x) - x), abs(int(actor.y) - y)) <= radius)
        if kind == "Campaign Rescue Count":
            return int(self._campaign_rescue_totals.get(int(args.get("player", player)), 0))
        if kind == "Campaign Capture Count":
            return int(self._campaign_capture_totals.get(int(args.get("player", player)), 0))
        if kind == "Campaign Rescue Possible":
            owner = int(args.get("player", player))
            required = max(0, int(args.get("required", self._campaign_rescue_goal.get(owner, 0))))
            already = int(self._campaign_rescue_totals.get(owner, 0))
            available = 0
            snapshot = getattr(self, "_snapshot", {})
            for key in getattr(self, "_source128_rescue_enabled", set()):
                if key in snapshot:
                    available += 1
            return int(already + available >= required)
        if kind == "Campaign Rescue Goal Met":
            owner = int(args.get("player", player))
            required = int(self._campaign_rescue_goal.get(owner, 0))
            return int(required > 0 and int(self._campaign_rescue_totals.get(owner, 0)) >= required)
        if kind == "Campaign Player Eliminated":
            owner = int(args.get("player", player))
            return int(self._campaign_non_auxiliary_mobile_count(owner) == 0 and self._campaign_building_count(owner) == 0)
        if kind == "Campaign Player Alive":
            owner = int(args.get("player", player))
            return int(self._campaign_non_auxiliary_mobile_count(owner) > 0 or self._campaign_building_count(owner) > 0)
        if kind == "Campaign Genocide Complete":
            target = int(args.get("target_player", -1))
            owners = [target] if target >= 0 else [owner for owner in range(8) if owner != int(player)]
            return int(all(self._campaign_non_auxiliary_mobile_count(owner) == 0 and self._campaign_building_count(owner) == 0 for owner in owners))
        if kind == "Campaign Unit Type Remaining":
            owner = int(args.get("player", player)); unit_type = int(args.get("unit", 0))
            return sum(1 for unit in self.units() if int(unit.owner) == owner and int(unit.unit_type) == unit_type and not (int(unit.sflags) & DEAD_FLAG_MASK))
        if kind == "Campaign Unit Type Destroyed":
            owner = int(args.get("player", player)); unit_type = int(args.get("unit", 0))
            return int(not any(int(unit.owner) == owner and int(unit.unit_type) == unit_type and not (int(unit.sflags) & DEAD_FLAG_MASK) for unit in self.units()))
        if kind == "Campaign Completed Building Count":
            owner = int(args.get("player", player)); unit_type = args.get("unit", "Any")
            return sum(1 for unit in self.units() if int(unit.owner) == owner and int(unit.unit_type) >= 58 and (unit_type == "Any" or int(unit.unit_type) == int(unit_type)) and int(unit.sflags) & SF_COMPLETED and not (int(unit.sflags) & DEAD_FLAG_MASK))
        if kind == "Campaign Building Type Destroyed":
            owner = int(args.get("player", player)); unit_type = int(args.get("unit", 58))
            return int(not any(int(unit.owner) == owner and int(unit.unit_type) == unit_type and int(unit.unit_type) >= 58 and not (int(unit.sflags) & DEAD_FLAG_MASK) for unit in self.units()))
        if kind == "Campaign All Actors In Location":
            raw = str(args.get("actors", "")).replace(";", ",")
            names = [part.strip() for part in raw.split(",") if part.strip()]
            if not names:
                return 0
            x, y = self._campaign_point(args, key="location")
            radius = max(0, int(args.get("radius", 0)))
            for name in names:
                actor = self._resolve_unit_reference(name)
                if actor is None or max(abs(int(actor.x) - x), abs(int(actor.y) - y)) > radius:
                    return 0
            return 1
        if kind == "Campaign All Actors Alive":
            raw = str(args.get("actors", "")).replace(";", ",")
            names = [part.strip() for part in raw.split(",") if part.strip()]
            return int(bool(names) and all(self._campaign_actor_state(name) == "Alive" for name in names))
        if kind == "Campaign Any Actor Dead":
            raw = str(args.get("actors", "")).replace(";", ",")
            names = [part.strip() for part in raw.split(",") if part.strip()]
            return int(any(self._campaign_actor_state(name) in {"Dead", "Removed", "Missing"} for name in names))
        return super().massive_value(kind, args, player)

    # ------------------------------------------------------------------ actions
    def massive_action(self, kind: str, args: dict[str, Any], player: int) -> bool:
        # ------------------------------ campaign objective / briefing layer
        if kind in {"Set Campaign Objective", "Complete Campaign Objective", "Fail Campaign Objective", "Hide Campaign Objective", "Show Campaign Objective", "Clear Campaign Objective"}:
            # Trigger-authored objective mutations always win over PUD/campaign
            # text until Restore Map Objectives is explicitly executed.
            self._campaign_objective_override_active = True
            name = str(args.get("name", "Objective 1")).strip()
            if kind == "Clear Campaign Objective":
                self._campaign_objectives.pop(name, None)
                self.objectives.pop(name, None); self.completed_objectives.discard(name)
                message = f"OBJECTIVE REMOVED: {name}"
            else:
                record = self._campaign_objective(name, create=True, text=str(args.get("text", name)) if kind == "Set Campaign Objective" else None)
                assert record is not None
                if kind == "Set Campaign Objective": record["state"] = "Active"
                elif kind == "Complete Campaign Objective": record["state"] = "Completed"
                elif kind == "Fail Campaign Objective": record["state"] = "Failed"
                elif kind == "Hide Campaign Objective": record["state"] = "Hidden"
                elif kind == "Show Campaign Objective" and record.get("state") == "Hidden": record["state"] = "Active"
                self.objectives[name] = str(record.get("text", name))
                if record["state"] == "Completed": self.completed_objectives.add(name)
                else: self.completed_objectives.discard(name)
                message = f"OBJECTIVE {str(record['state']).upper()}: {record['text']}"
            self._campaign_hud_next = 0.0
            self._native_objectives_rearm_next = 0.0
            self.log(message)
            if bool(args.get("announce", True)) and kind not in {"Hide Campaign Objective", "Show Campaign Objective"}:
                self._game_message({"text": message, "color": args.get("color", "Yellow / gold — native normal"), "recipients": args.get("recipients", "All active players"), "seconds": int(args.get("seconds", 4)), "also_log": False}, player)
            return True
        if kind == "Clear All Campaign Objectives":
            # An intentionally empty trigger objective list still overrides the
            # map list; Restore Map Objectives is the explicit hand-back action.
            self._campaign_objective_override_active = True
            self._campaign_objectives.clear(); self.objectives.clear(); self.completed_objectives.clear(); self._campaign_hud_next = 0.0; self._native_objectives_rearm_next = 0.0; return True
        if kind == "Use Trigger Objectives":
            self._campaign_objective_override_active = True
            self._native_objectives_rearm_next = 0.0
            self.log("OBJECTIVE SOURCE: trigger objectives override the map")
            return True
        if kind == "Restore Map Objectives":
            self._campaign_objective_override_active = False
            self._campaign_hud_visible = False
            self._free_pending_native_objectives()
            self._native_objectives_pending_signature = None
            self.log("OBJECTIVE SOURCE: restored native map/campaign objectives")
            return True
        if kind == "Show Objectives HUD":
            # 1.38: this prepares the allocator-free native in-game objective
            # renderer view. Open Scenario Objectives uses Warcraft's own pause-menu
            # opener on the main simulation thread.
            self._campaign_hud_visible = True
            if self._campaign_objective_override_active:
                self._stage_native_objectives()
            return True
        if kind == "Hide Objectives HUD":
            self._campaign_hud_visible = False; self._campaign_hud_pending_text = None; return True
        if kind == "Refresh Objectives HUD":
            if self._campaign_objective_override_active:
                self._stage_native_objectives()
            return True
        if kind in {"Show Native Objectives", "Open Scenario Objectives", "Show Native Objectives HUD (Experimental)", "Open Native Scenario Objectives (Experimental)"}:
            return self._open_native_objectives()
        if kind == "Set Rescue Goal":
            owner = int(args.get("player", player)); self._campaign_rescue_goal[owner] = max(0, int(args.get("amount", 0))); return True

        if kind == "Show Mission Briefing":
            title = str(args.get("title", "Mission Briefing")).strip()
            story = str(args.get("story", "")).strip()
            objectives = str(args.get("objectives", "")).strip() or "\n".join(f"- {r['text']}" for _, r in sorted(self._campaign_objectives.items(), key=lambda item: int(item[1].get('order', 0))) if r.get("state") != "Hidden")
            self._campaign_briefing = {"title": title, "story": story, "objectives": objectives}
            body = title
            if story: body += "\n\n" + story
            if objectives: body += "\n\nOBJECTIVES\n" + objectives
            return self._campaign_timed_message("campaign_briefing", body, float(args.get("seconds", 8.0)), player, color=str(args.get("color", "White — native highlight")), recipients=str(args.get("recipients", "All active players")))
        if kind == "Show Act Card":
            title = str(args.get("title", "ACT I")); subtitle = str(args.get("subtitle", "")); body = title + (("\n" + subtitle) if subtitle else "")
            return self._campaign_timed_message("campaign_act_card", body, float(args.get("seconds", 4.0)), player, color=str(args.get("color", "White — native highlight")), recipients=str(args.get("recipients", "All active players")))
        if kind in {"Show Epilogue", "Show Credits"}:
            text = str(args.get("text", "")) or ("VICTORY" if kind == "Show Epilogue" else "CREDITS")
            return self._campaign_timed_message("campaign_" + kind.casefold().replace(" ", "_"), text, float(args.get("seconds", 10.0)), player, color=str(args.get("color", "White — native highlight")), recipients=str(args.get("recipients", "All active players")))

        # ---------------------------------------------------- cutscene director
        if kind == "Begin Cutscene":
            if not self._campaign_cutscene_active:
                self._campaign_saved_camera = self._campaign_current_camera()
            self._campaign_cutscene_active = True
            self._campaign_cutscene_label = str(args.get("name", "Cutscene"))
            # Source 1.28 input lock is explicitly a local-authoring state marker;
            # we keep it in sync but do not pretend it hooks Remaster input.
            self._source128_input_locked = bool(args.get("mark_input_locked", True))
            if bool(args.get("hide_objectives", True)):
                self._campaign_hud_visible = False
            if bool(args.get("deselect_units", True)):
                for unit in self.units():
                    try:
                        flags = self.pm.read_ushort(unit.address + 0x1E)
                        if flags & 0x2000:
                            self.pm.write_ushort(unit.address + 0x1E, flags & ~0x2000)
                    except Exception:
                        pass
            self.log(f"CUTSCENE BEGIN: {self._campaign_cutscene_label}")
            return True
        if kind == "End Cutscene":
            restore = bool(args.get("restore_camera", True))
            saved = self._campaign_saved_camera
            if restore and saved is not None:
                self._campaign_camera_call(*saved)
            self._campaign_cutscene_active = False
            self._source128_input_locked = False
            self._campaign_camera_motion = None
            self._campaign_camera_follow = None
            self._campaign_camera_shake = None
            self.log(f"CUTSCENE END: {self._campaign_cutscene_label or 'Cutscene'}")
            self._campaign_cutscene_label = ""; self._campaign_saved_camera = None
            return True

        if kind == "Scene Create Actor":
            actor_name = str(args.get("actor", "Actor")).strip()
            state = self._cached_action_value("scene_create_actor", lambda: {"before": {int(u.address) for u in self.units()}, "done": False})
            if not state["done"]:
                owner = int(args.get("player", player)); unit_type = int(args.get("unit", 8))
                x, y = self._campaign_point(args, key="location")
                self.action("Create Units", {"player": owner, "new_unit": unit_type, "amount": 1, "location": "Anywhere", "x": x, "y": y}, player)
                created = [u for u in self.units() if int(u.address) not in state["before"] and int(u.owner) == owner and int(u.unit_type) == unit_type]
                if not created:
                    raise RuntimeError(f"Scene Create Actor could not locate the newly-created unit {unit_type}")
                unit = min(created, key=lambda u: (int(u.x)-x)**2 + (int(u.y)-y)**2)
                self._campaign_register_actor(actor_name, unit, created=True)
                if "facing" in args:
                    self.pm.write_uchar(unit.address + 0x0A, int(args.get("facing", 0)) & 7)
                if bool(args.get("invincible", False)):
                    self.pm.write_ushort(unit.address + 0x46, 0xFFFF)
                state["done"] = True
                self.log(f"SCENE ACTOR: {actor_name} = P{owner+1} type {unit_type} at ({unit.x},{unit.y})")
            return True
        if kind == "Scene Save Actor":
            actor_name = str(args.get("actor", "Actor")); unit = self._pick_reference_unit(args, player); self._campaign_register_actor(actor_name, unit, created=False); return True
        if kind == "Scene Clear Actor":
            name = str(args.get("actor", "Actor")); self.unit_references.pop(name, None); self._campaign_actor_status[name] = "Missing"; return True

        if kind == "Scene Actor Talk":
            actor_name = str(args.get("actor", "Actor")); actor = self._campaign_actor(actor_name)
            seconds = max(0.1, float(args.get("seconds", 4.0)))
            state = self._cached_action_value("scene_actor_talk", lambda: {"started": time.monotonic(), "published": False})
            if not state["published"]:
                speaker = str(args.get("speaker", actor_name)); text = str(args.get("text", "")); message = f"{speaker}: {text}" if speaker else text
                if bool(args.get("center_camera", False)):
                    self._campaign_camera_call(int(actor.x), int(actor.y))
                if bool(args.get("voice_bark", True)):
                    self._call_cdecl(self.source_native_paths["gamesnd_select"], [actor.address])
                self._game_message({"text": message, "color": args.get("color", "White — native highlight"), "recipients": args.get("recipients", "All active players"), "seconds": max(1, int(math.ceil(seconds))), "also_log": True}, player)
                state["published"] = True
                self._campaign_scene_log.append(message)
            if bool(args.get("wait", True)) and time.monotonic() - float(state["started"]) < seconds:
                raise ActionDeferred(f"{actor_name} is still speaking", retry_after=0.10)
            return True

        if kind in {"Scene Actor Walk", "Scene Actor Patrol"}:
            actor_name = str(args.get("actor", "Actor")); actor = self._campaign_actor(actor_name)
            x, y = self._campaign_point(args)
            callback = self.order_callees["do_move" if kind.endswith("Walk") else "do_patrol"]
            state = self._cached_action_value("scene_actor_move", lambda: {"started": time.monotonic(), "ordered": False, "x": x, "y": y, "address": int(actor.address)})
            if not state["ordered"]:
                self._call_cdecl(self.order_callees["set_target"], [actor.address, x, y, 0, callback]); state["ordered"] = True
            if not bool(args.get("wait_for_arrival", True)):
                return True
            actor = self._campaign_actor(actor_name)
            radius = max(0, int(args.get("arrival_radius", 1)))
            if max(abs(int(actor.x)-x), abs(int(actor.y)-y)) <= radius:
                return True
            timeout = max(0.0, float(args.get("timeout", 30.0)))
            if timeout and time.monotonic() - float(state["started"]) >= timeout:
                behavior = str(args.get("on_timeout", "Continue"))
                if behavior == "Teleport":
                    moved = self._move_mobile_unit(actor, x, y); self._save_reference(actor_name, moved); return True
                if behavior == "Error":
                    raise RuntimeError(f"{actor_name} did not reach ({x},{y}) within {timeout:g}s")
                return True
            raise ActionDeferred(f"Waiting for {actor_name} to reach ({x},{y})", retry_after=0.10)

        if kind == "Scene Actor Attack":
            actor_name = str(args.get("actor", "Actor")); actor = self._campaign_actor(actor_name)
            target_name = str(args.get("target_actor", "")).strip()
            target = self._resolve_unit_reference(target_name) if target_name else None
            if target is not None:
                x, y, target_ptr = int(target.x), int(target.y), int(target.address)
            else:
                x, y = self._campaign_point(args); target_ptr = 0
            state = self._cached_action_value("scene_actor_attack", lambda: {"ordered": False, "started": time.monotonic(), "target": target_name})
            if not state["ordered"]:
                self._call_cdecl(self.order_callees["set_target"], [actor.address, x, y, target_ptr, self.order_callees["do_attack"]]); state["ordered"] = True
            if bool(args.get("wait_for_target_death", False)) and target_name and self._resolve_unit_reference(target_name) is not None:
                timeout = max(0.0, float(args.get("timeout", 30.0)))
                if not timeout or time.monotonic() - float(state["started"]) < timeout:
                    raise ActionDeferred(f"Waiting for {target_name} to die", retry_after=0.10)
            return True

        if kind in {"Scene Actor Guard", "Scene Actor Stop"}:
            actor = self._campaign_actor(args.get("actor", "Actor"))
            callback = self.source_native_paths.get("do_guard", self.order_callees.get("do_move"))
            self._call_cdecl(self.order_callees["set_target"], [actor.address, int(actor.x), int(actor.y), 0, callback]); return True

        if kind == "Scene Actor Face":
            actor = self._campaign_actor(args.get("actor", "Actor")); facing = int(args.get("facing", 0)) & 7
            self._dispatch_ops([("write_byte", actor.address + 0x0A, facing), ("or_byte", actor.address + 0x06, 0x20)]); return True
        if kind == "Scene Actor Look At Actor":
            actor = self._campaign_actor(args.get("actor", "Actor")); target = self._campaign_actor(args.get("target_actor", "Target"))
            dx, dy = int(target.x)-int(actor.x), int(target.y)-int(actor.y)
            angle = math.atan2(dy, dx)
            # Warcraft: 0=N, 2=E, 4=S, 6=W.
            facing = int(round(((angle + math.pi/2) % (2*math.pi)) / (math.pi/4))) & 7
            self._dispatch_ops([("write_byte", actor.address + 0x0A, facing), ("or_byte", actor.address + 0x06, 0x20)]); return True
        if kind == "Scene Actor Play Animation":
            actor = self._campaign_actor(args.get("actor", "Actor"))
            animation = max(0, min(255, int(args.get("animation", 0)))); frame = max(0, min(255, int(args.get("frame", 0)))); facing = int(args.get("facing", self.pm.read_uchar(actor.address+0x0A))) & 7; timer = max(0, min(255, int(args.get("timer", 1))))
            self._dispatch_ops([("write_byte", actor.address+0x07, timer), ("write_byte", actor.address+0x08, animation), ("write_byte", actor.address+0x09, frame), ("write_byte", actor.address+0x0A, facing), ("or_byte", actor.address+0x06, 0x20)])
            duration = max(0.0, float(args.get("seconds", 0.0)))
            if duration:
                state = self._cached_action_value("scene_actor_animation", lambda: {"started": time.monotonic()})
                if time.monotonic() - float(state["started"]) < duration:
                    raise ActionDeferred("Scene animation still playing", retry_after=0.10)
            return True
        if kind == "Scene Actor Die":
            name = str(args.get("actor", "Actor")); actor = self._campaign_actor(name); self._call_cdecl(self.damage_callees["unit_kill"], [actor.address]); self._campaign_actor_status[name] = "Dead"; return True
        if kind == "Scene Actor Remove":
            name = str(args.get("actor", "Actor")); actor = self._campaign_actor(name); self._remove_one_unit_safely(actor); self._campaign_actor_status[name] = "Removed"; self.unit_references.pop(name, None); return True
        if kind == "Scene Actor Hide":
            name = str(args.get("actor", "Actor")); actor = self._campaign_actor(name); flags = self.pm.read_ushort(actor.address+0x1E)
            self._dispatch_ops([("call", self.move_callees["cancel_tree_harvest"], [actor.address]), ("call", self.move_callees["unplace_man"], [actor.address]), ("write_word", actor.address+0x1E, flags|SF_HIDDEN)])
            self._campaign_actor_status[name] = "Hidden"; return True
        if kind == "Scene Actor Show":
            name = str(args.get("actor", "Actor")); actor = self._campaign_actor(name); self.pm.write_ushort(actor.address+0x1E, self.pm.read_ushort(actor.address+0x1E)&~SF_HIDDEN)
            point = self._find_move_place(actor, max(0, int(actor.x)), max(0, int(actor.y)))
            if point: actor = self._move_mobile_unit(actor, *point); self._save_reference(name, actor)
            self._campaign_actor_status[name] = "Alive"; return True
        if kind == "Scene Actor Teleport":
            name = str(args.get("actor", "Actor")); actor = self._campaign_actor(name); x,y = self._campaign_point(args); moved = self._move_mobile_unit(actor,x,y); self._save_reference(name,moved); return True
        if kind == "Scene Actor Set HP":
            name = str(args.get("actor", "Actor")); self._campaign_actor(name)
            return super().massive_action("Set Unit Reference Health", {"reference": name, "amount": int(args.get("amount", 100))}, player)
        if kind == "Scene Actor Set Mana":
            name = str(args.get("actor", "Actor")); self._campaign_actor(name)
            return super().massive_action("Set Unit Reference Mana", {"reference": name, "amount": int(args.get("amount", 255))}, player)
        if kind == "Scene Actor Damage From Actor":
            target = self._campaign_actor(args.get("actor", "Actor")); attacker = self._campaign_actor(args.get("attacker_actor", "Attacker"))
            damage = max(1, min(255, int(args.get("amount", 20))))
            self._call_damage_unit(attacker, target, damage)
            return True
        if kind == "Scene Actor Change Owner":
            name = str(args.get("actor", "Actor")); actor = self._campaign_actor(name); new_owner = int(args.get("new_owner", player))
            self._call_cdecl(self.capture_unit_address, [actor.address, new_owner, 0])
            refreshed = next((u for u in self.units() if int(u.address) == int(actor.address)), None)
            self._campaign_register_actor(name, refreshed, created=bool(self._campaign_actor_meta.get(name, {}).get("created", False)))
            return True
        if kind in {"Scene Actor Invincible", "Scene Actor Vulnerable"}:
            actor = self._campaign_actor(args.get("actor", "Actor")); self.pm.write_ushort(actor.address+0x46, 0xFFFF if kind.endswith("Invincible") else 0); return True
        if kind in {"Scene Actor Rescuable", "Scene Actor Not Rescuable"}:
            actor = self._campaign_actor(args.get("actor", "Actor")); key = self._source_unit_key(actor)
            flags = self.pm.read_ushort(actor.address+0x1C)
            if kind.endswith("Rescuable") and not kind.startswith("Scene Actor Not"):
                self._source128_rescue_enabled.add(key); self.pm.write_ushort(actor.address+0x1C, flags|0x0100)
            else:
                self._source128_rescue_enabled.discard(key); self.pm.write_ushort(actor.address+0x1C, flags&~0x0100)
            return True
        if kind == "Scene Wait For Actor State":
            name = str(args.get("actor", "Actor")); wanted = str(args.get("state", "Dead"))
            state = self._cached_action_value("scene_wait_actor_state", lambda: {"started": time.monotonic()})
            if self._campaign_actor_state(name) == wanted:
                return True
            timeout = max(0.0, float(args.get("timeout", 0.0)))
            if timeout and time.monotonic() - float(state["started"]) >= timeout:
                if str(args.get("on_timeout", "Continue")) == "Error":
                    raise RuntimeError(f"{name} did not reach state {wanted} within {timeout:g}s")
                return True
            raise ActionDeferred(f"Waiting for {name} state {wanted}", retry_after=0.10)
        if kind in {"Scene Wait For Actor At Location", "Scene Wait For All Actors At Location"}:
            state = self._cached_action_value("scene_wait_actor_location", lambda: {"started": time.monotonic()})
            x, y = self._campaign_point(args); radius = max(0, int(args.get("radius", 1)))
            if kind == "Scene Wait For Actor At Location":
                names = [str(args.get("actor", "Actor"))]
            else:
                raw = str(args.get("actors", "")).replace(";", ",")
                names = [part.strip() for part in raw.split(",") if part.strip()]
            ready = bool(names)
            for name in names:
                actor = self._resolve_unit_reference(name)
                if actor is None or max(abs(int(actor.x)-x), abs(int(actor.y)-y)) > radius:
                    ready = False; break
            if ready:
                return True
            timeout = max(0.0, float(args.get("timeout", 30.0)))
            if timeout and time.monotonic() - float(state["started"]) >= timeout:
                if str(args.get("on_timeout", "Continue")) == "Error":
                    raise RuntimeError(f"Actors did not reach ({x},{y}) within {timeout:g}s")
                return True
            raise ActionDeferred(f"Waiting for scene actors at ({x},{y})", retry_after=0.10)

        # ------------------------------------------------------------ camera
        if kind == "Scene Camera Cut":
            x,y = self._campaign_point(args); self._campaign_camera_motion=None; self._campaign_camera_call(x,y); return True
        if kind == "Scene Camera Pan":
            x,y = self._campaign_point(args); duration=max(0.05,float(args.get("seconds",2.0)))
            owner = tuple(self._action_context) if self._action_context is not None else None
            state = self._cached_action_value("scene_camera_pan", lambda: {"started": False, "owner": owner})
            if not state["started"]:
                start = self._campaign_current_camera() or (x,y)
                steps=max(2,min(120,int(math.ceil(duration/max(0.05,float(args.get("step_seconds",0.08)))))))
                self._campaign_camera_motion={"owner":owner,"sx":start[0],"sy":start[1],"tx":x,"ty":y,"steps":steps,"index":0,"step_seconds":duration/steps,"next":time.monotonic(),"done":False}
                self._campaign_camera_follow=None; state["started"]=True
            if self._campaign_camera_motion is not None:
                raise ActionDeferred(f"Camera panning to ({x},{y})",retry_after=0.08)
            return True
        if kind == "Scene Camera Follow Actor":
            actor_name=str(args.get("actor","Actor")); self._campaign_actor(actor_name); self._campaign_camera_motion=None; self._campaign_camera_follow={"actor":actor_name,"cadence":max(0.10,float(args.get("cadence",0.20))),"last":(-999,-999),"pending":None}; self._campaign_camera_next=0.0; return True
        if kind == "Scene Stop Camera Follow":
            self._campaign_camera_follow=None; return True
        if kind == "Scene Camera Shake":
            magnitude=max(1,int(args.get("magnitude",1))); duration=max(0.1,float(args.get("seconds",0.75)))
            state=self._cached_action_value("scene_camera_shake",lambda:{"started":False})
            if not state["started"]:
                self._campaign_camera_motion=None
                self._campaign_camera_follow=None
                self._campaign_camera_shake={"started":time.monotonic(),"duration":duration,"magnitude":magnitude,"base":self._campaign_current_camera() or (0,0),"next":time.monotonic(),"pending":None}
                state["started"]=True
            if self._campaign_camera_shake is not None:
                raise ActionDeferred("Camera shake active",retry_after=0.10)
            return True
        if kind == "Scene Play Sound":
            actor_name=str(args.get("actor","")).strip()
            if actor_name:
                actor=self._campaign_actor(actor_name); event=str(args.get("event","Selection"))
                callback={"Selection":"gamesnd_select","Under Attack":"gamesnd_under_attack","Harvest":"gamesnd_harvest","Unit Death":"gamesnd_kill_man","Building Destruction":"gamesnd_kill_bldg"}.get(event)
                if callback: self._call_cdecl(self.source_native_paths[callback],[actor.address])
                else: self._call_cdecl(self.source_native_paths["gamesnd_spell"],[actor.address,self._spell_sound_id(args.get("sound","Thunder"))])
            else:
                x,y=self._campaign_point(args); self._call_cdecl(self.source_native_paths["gamesnd_explode"],[x,y])
            return True

        return super().massive_action(kind, args, player)
