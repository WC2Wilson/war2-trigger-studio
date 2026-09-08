from __future__ import annotations

import base64
import ctypes
import json
import shutil
import struct
import subprocess
import sys
import time
from ctypes import wintypes
from typing import Any

from engine import ActionDeferred
from mission_features_130 import MissionFeature130Mixin
from compatibility import resolve_victory_layout


# legacy reference module / reference module:
#   #define CHEAT_NOVICTORY 0x00000200
#   victory_update(): when single-player/non-demo and this bit is set, return
#   before *all* stock victory/loss checks.
CHEAT_NOVICTORY = 0x00000200

# Warcraft II Remastered x86 1.0.2.2818 source-correlated victory_update.
# Preferred VA 0x004F4F60 -> RVA 0x000F4F60.
VICTORY_UPDATE_RVA_2818 = 0x000F4F60
MULTIPLAYER_GATE_RVA_2818 = 0x00522F5B
DEMO_MODE_RVA_2818 = 0x0051BCD4
CHEAT_BITS_RVA_2818 = 0x0051B270

# Windows virtual-key names used by local scene-choice / skip conditions.
_LOCAL_KEYS = {
    "Escape": 0x1B,
    "Space": 0x20,
    "Enter": 0x0D,
    "Tab": 0x09,
    "Backspace": 0x08,
    "Left": 0x25,
    "Up": 0x26,
    "Right": 0x27,
    "Down": 0x28,
    **{str(i): 0x30 + i for i in range(10)},
    **{chr(ord("A") + i): 0x41 + i for i in range(26)},
    **{f"F{i}": 0x6F + i for i in range(1, 13)},
}


class MissionFeature131Mixin(MissionFeature130Mixin):
    """1.31 blank-map bootstrap, trigger-controlled results, and local scene TTS.

    The startup guard and the runtime trigger action intentionally use two
    different mechanisms:

    * Pre-map guard: one-byte, validated `victory_update -> ret` bridge. This can
      be armed while Warcraft is still at the menus, so a genuinely empty map
      cannot auto-end before Trigger Studio has time to attach.
    * Runtime control: source-native CHEAT_NOVICTORY bit 0x200. Once the scenario
      trigger engine is running, `Blank Map Bootstrap` sets the bit and restores
      the temporary entry patch, leaving Warcraft's normal updater intact but
      skipping its stock victory/loss logic. Explicit Victory/Defeat actions still
      work because they call the validated game_set_mode path directly.

    TTS uses Windows' installed System.Speech/SAPI voices through powershell.exe.
    No cloud key and no extra Python package are required. Male/Female selection
    is based on each installed voice's VoiceInfo.Gender.
    """

    def _init_massive_features(self) -> None:
        super()._init_massive_features()
        self._mission131_tts_processes: list[subprocess.Popen] = []
        self._mission131_tts_voice_cache: list[dict[str, str]] | None = None
        self._mission131_key_down: dict[int, bool] = {}
        self._mission131_trigger_results_enabled = False
        self._mission131_blank_bridge_seen = False
        self._mission131_victory_layout_cache = None

    def _massive_begin_run(self) -> None:
        super()._massive_begin_run()
        self._mission131_key_down.clear()
        self._mission131_trigger_results_enabled = False
        self._mission131_blank_bridge_seen = False
        self._mission131_victory_layout_cache = None
        self._mission131_cleanup_tts(done_only=True)

    # ------------------------------------------------------------ win/loss guard
    def _mission131_victory_layout(self, *, refresh: bool = False) -> dict[str, int | bytes]:
        if self._mission131_victory_layout_cache is None or refresh:
            self._mission131_victory_layout_cache = resolve_victory_layout(
                self.pm, self.base, int(getattr(self, "image_size", 0) or 0x0062B000)
            )
        return dict(self._mission131_victory_layout_cache)

    def _mission131_victory_signature(self) -> bytes:
        return bytes(self._mission131_victory_layout(refresh=True)["signature"])

    def _mission131_victory_patch_state(self) -> str:
        """Return Original, Armed, or Unknown for the source-correlated victory_update."""
        layout = self._mission131_victory_layout(refresh=True)
        expected = bytes(layout["signature"])
        addr = int(layout["victory_update"])
        current = bytes(self.pm.read_bytes(addr, len(expected)))
        if current == expected:
            return "Original"
        if current[:1] == b"\xC3" and current[1:] == expected[1:]:
            return "Armed"
        return "Unknown"

    def _mission131_restore_blank_bridge(self) -> bool:
        layout = self._mission131_victory_layout(refresh=True)
        state = self._mission131_victory_patch_state()
        if state == "Original":
            return False
        if state != "Armed":
            raise RuntimeError(
                "victory_update is modified by something other than the validated Blank Map Guard; refusing to overwrite it"
            )
        self._write_executable_bytes(int(layout["victory_update"]), b"\x80")
        self._mission131_victory_layout_cache = None
        if self._mission131_victory_patch_state() != "Original":
            raise RuntimeError("Blank Map Guard restore verification failed")
        return True

    def _mission131_set_novictory_bit(self, enabled: bool) -> tuple[int, int]:
        layout = self._mission131_victory_layout()
        addr = int(layout["cheat_bits"])
        before = int(self.pm.read_uint(addr))
        after = (before | CHEAT_NOVICTORY) if enabled else (before & ~CHEAT_NOVICTORY)
        if after != before:
            self._dispatch_ops([("write_dword", addr, after)])
        verified = int(self.pm.read_uint(addr))
        if verified != after:
            raise RuntimeError(
                f"CHEAT_NOVICTORY verification failed: 0x{before:08X} -> expected 0x{after:08X}, read 0x{verified:08X}"
            )
        return before, verified

    def _mission131_enable_trigger_results(self, *, restore_bridge: bool = True) -> None:
        layout = self._mission131_victory_layout(refresh=True)
        multiplayer = int(self.pm.read_uchar(int(layout["multiplayer"])))
        if multiplayer:
            raise RuntimeError(
                "Trigger-controlled win/loss is intentionally single-player only. The original victory_update ignores CHEAT_NOVICTORY in multiplayer, and keeping the code bridge active in a synchronized match could desync clients."
            )
        before, after = self._mission131_set_novictory_bit(True)
        restored = False
        if restore_bridge:
            restored = self._mission131_restore_blank_bridge()
        self._mission131_trigger_results_enabled = True
        self.game_state = "Playing"
        self.log(
            "TRIGGER-CONTROLLED RESULTS ENABLED: native automatic win/loss disabled "
            f"through source CHEAT_NOVICTORY 0x200 (CheatBits 0x{before:08X}->0x{after:08X}); "
            + ("pre-map victory_update RET bridge restored to native code" if restored else "native victory_update code already active")
            + "; explicit Victory/Defeat trigger actions remain available"
        )

    def _mission131_disable_trigger_results(self) -> None:
        restored = self._mission131_restore_blank_bridge()
        before, after = self._mission131_set_novictory_bit(False)
        self._mission131_trigger_results_enabled = False
        self.log(
            "NATIVE WIN/LOSS RESTORED: "
            f"CheatBits 0x{before:08X}->0x{after:08X}"
            + ("; removed pre-map bridge" if restored else "")
        )

    def _mission131_results_suppressed(self) -> bool:
        layout = self._mission131_victory_layout(refresh=True)
        bits = int(self.pm.read_uint(int(layout["cheat_bits"])))
        bit = bool(bits & CHEAT_NOVICTORY)
        try:
            bridge = self._mission131_victory_patch_state() == "Armed"
        except Exception:
            bridge = False
        return bit or bridge

    # ---------------------------------------------------------------- local keys
    @staticmethod
    def _mission131_vk(name: Any) -> int:
        text = str(name or "Escape").strip()
        if text in _LOCAL_KEYS:
            return _LOCAL_KEYS[text]
        upper = text.upper()
        for key, value in _LOCAL_KEYS.items():
            if key.upper() == upper:
                return value
        if upper.startswith("VK_"):
            upper = upper[3:]
            for key, value in _LOCAL_KEYS.items():
                if key.upper() == upper:
                    return value
        try:
            value = int(text, 0)
            if 0 <= value <= 0xFF:
                return value
        except Exception:
            pass
        raise ValueError(f"Unsupported local key: {text}")

    def _mission131_key_state(self, vk: int) -> bool:
        if not sys.platform.startswith("win"):
            return False
        try:
            return bool(ctypes.windll.user32.GetAsyncKeyState(int(vk)) & 0x8000)
        except Exception:
            return False

    # ---------------------------------------------------------------------- TTS
    @staticmethod
    def _mission131_powershell() -> str | None:
        # Prefer Windows PowerShell 5.1 because System.Speech is part of the
        # desktop .NET Framework there. pwsh is a fallback only.
        return shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh.exe") or shutil.which("pwsh")

    @staticmethod
    def _mission131_ps_encoded(script: str) -> str:
        return base64.b64encode(script.encode("utf-16le")).decode("ascii")

    def _mission131_tts_voices(self, *, refresh: bool = False) -> list[dict[str, str]]:
        if self._mission131_tts_voice_cache is not None and not refresh:
            return list(self._mission131_tts_voice_cache)
        ps = self._mission131_powershell()
        if not ps:
            self._mission131_tts_voice_cache = []
            return []
        script = r'''
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$rows = @()
foreach($v in $s.GetInstalledVoices()) {
  if($v.Enabled) {
    $i=$v.VoiceInfo
    $rows += [pscustomobject]@{Name=$i.Name; Gender=$i.Gender.ToString(); Culture=$i.Culture.Name; Age=$i.Age.ToString()}
  }
}
$rows | ConvertTo-Json -Compress
'''
        try:
            cp = subprocess.run(
                [ps, "-NoProfile", "-NonInteractive", "-EncodedCommand", self._mission131_ps_encoded(script)],
                capture_output=True, text=True, timeout=12,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if cp.returncode != 0:
                self.log("TTS VOICE QUERY FAILED: " + (cp.stderr.strip() or f"PowerShell exit {cp.returncode}"))
                rows: list[dict[str, str]] = []
            else:
                raw = cp.stdout.strip()
                parsed = json.loads(raw) if raw else []
                if isinstance(parsed, dict):
                    parsed = [parsed]
                rows = [
                    {"Name": str(row.get("Name", "")), "Gender": str(row.get("Gender", "")), "Culture": str(row.get("Culture", "")), "Age": str(row.get("Age", ""))}
                    for row in parsed if isinstance(row, dict) and row.get("Name")
                ]
        except Exception as exc:
            self.log(f"TTS VOICE QUERY FAILED: {exc}")
            rows = []
        self._mission131_tts_voice_cache = rows
        return list(rows)

    def _mission131_cleanup_tts(self, *, done_only: bool = False) -> None:
        kept: list[subprocess.Popen] = []
        for proc in list(getattr(self, "_mission131_tts_processes", [])):
            try:
                done = proc.poll() is not None
                if not done and not done_only:
                    proc.terminate()
                    try:
                        proc.wait(timeout=1.0)
                    except Exception:
                        proc.kill()
                        proc.wait(timeout=1.0)
                    done = True
                if not done:
                    kept.append(proc)
            except Exception:
                pass
        self._mission131_tts_processes = kept

    def _mission131_tts_spawn(
        self,
        *,
        text: str,
        gender: str = "Auto",
        voice_name: str = "",
        rate: int = 0,
        volume: int = 100,
    ) -> subprocess.Popen:
        ps = self._mission131_powershell()
        if not ps:
            raise RuntimeError("Windows PowerShell was not found; local System.Speech TTS is unavailable")
        text_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        voice_b64 = base64.b64encode(voice_name.encode("utf-8")).decode("ascii")
        gender = str(gender or "Auto").strip().capitalize()
        if gender not in {"Auto", "Male", "Female", "Neutral"}:
            gender = "Auto"
        rate = max(-10, min(10, int(rate)))
        volume = max(0, min(100, int(volume)))
        script = f'''
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$text=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{text_b64}'))
$voice=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{voice_b64}'))
$gender='{gender}'
if($voice.Length -gt 0) {{
  $s.SelectVoice($voice)
}} elseif($gender -ne 'Auto') {{
  $matches=@($s.GetInstalledVoices() | Where-Object {{ $_.Enabled -and $_.VoiceInfo.Gender.ToString() -eq $gender }})
  if($matches.Count -eq 0) {{ throw "No enabled System.Speech $gender voice is installed. Run 'List TTS Voices' in Trigger Studio to see available voices." }}
  $s.SelectVoice($matches[0].VoiceInfo.Name)
}}
$s.Rate={rate}
$s.Volume={volume}
$s.Speak($text)
'''
        proc = subprocess.Popen(
            [ps, "-NoProfile", "-NonInteractive", "-EncodedCommand", self._mission131_ps_encoded(script)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._mission131_tts_processes.append(proc)
        return proc

    def _mission131_tts_action(self, kind: str, args: dict[str, Any], player: int) -> bool:
        actor_name = str(args.get("actor", "Actor")).strip()
        text = str(args.get("text", "")).strip()
        if not text:
            raise ValueError(f"{kind} requires text")

        # The trigger engine retries deferred actions.  All visible/audio side effects
        # therefore belong inside the cached factory so subtitles, camera cuts and
        # speech are emitted exactly once for this action, not once per retry tick.
        def start_tts() -> dict[str, Any]:
            if kind == "Scene Actor TTS":
                actor = self._campaign_actor(actor_name)
                if bool(args.get("camera_cut", False)):
                    self._campaign_camera_motion = None
                    self._campaign_camera_follow = None
                    self._campaign_camera_call(int(actor.x), int(actor.y))
                if bool(args.get("subtitle", True)):
                    speaker = str(args.get("speaker", actor_name)).strip() or actor_name
                    self._game_message({
                        "text": f"{speaker}: {text}",
                        "color": str(args.get("color", "White — native highlight")),
                        "recipients": str(args.get("recipients", "All active players")),
                        "seconds": max(1, int(args.get("subtitle_seconds", 5))),
                        "also_log": bool(args.get("also_log", True)),
                    }, player)
            elif bool(args.get("subtitle", True)):
                speaker = str(args.get("speaker", "Narrator")).strip() or "Narrator"
                self._game_message({
                    "text": f"{speaker}: {text}",
                    "color": str(args.get("color", "White — native highlight")),
                    "recipients": str(args.get("recipients", "All active players")),
                    "seconds": max(1, int(args.get("subtitle_seconds", 5))),
                    "also_log": bool(args.get("also_log", True)),
                }, player)

            return {
                "proc": self._mission131_tts_spawn(
                    text=text,
                    gender=str(args.get("gender", "Auto")),
                    voice_name=str(args.get("voice_name", "")),
                    rate=int(args.get("rate", 0)),
                    volume=int(args.get("volume", 100)),
                ),
                "logged": False,
            }

        state = self._cached_action_value("mission131_tts", start_tts)
        proc = state["proc"]
        if not state["logged"]:
            self.log(
                f"TTS START v1.31: {kind}; gender={args.get('gender','Auto')}; "
                f"voice={args.get('voice_name','') or '<auto installed voice>'}; rate={int(args.get('rate',0))}; volume={int(args.get('volume',100))}"
            )
            state["logged"] = True
        if bool(args.get("wait", True)):
            rc = proc.poll()
            if rc is None:
                raise ActionDeferred("Waiting for local text-to-speech", retry_after=0.10)
            if rc != 0:
                try:
                    err = (proc.stderr.read() if proc.stderr else "").strip()
                except Exception:
                    err = ""
                raise RuntimeError(err or f"TTS PowerShell process exited {rc}")
        return True

    # ------------------------------------------------------------- conditions
    def massive_value(self, kind: str, args: dict[str, Any], player: int) -> Any:
        if kind == "Native Win/Loss Suppressed":
            return "Yes" if self._mission131_results_suppressed() else "No"
        if kind == "Blank Map Guard Armed":
            if int(getattr(self, "build_timestamp", 0)) != 0x699E13E7:
                return "No"
            try:
                return "Yes" if self._mission131_victory_patch_state() == "Armed" else "No"
            except Exception:
                return "No"
        if kind == "TTS Available":
            return "Yes" if bool(self._mission131_tts_voices()) else "No"
        if kind == "TTS Speaking":
            self._mission131_cleanup_tts(done_only=True)
            return "Yes" if any(proc.poll() is None for proc in self._mission131_tts_processes) else "No"
        if kind in {"Local Key Pressed", "Local Key Held"}:
            vk = self._mission131_vk(args.get("key", "Escape"))
            current = self._mission131_key_state(vk)
            if kind == "Local Key Held":
                self._mission131_key_down[vk] = current
                return 1 if current else 0
            previous = bool(self._mission131_key_down.get(vk, False))
            self._mission131_key_down[vk] = current
            return 1 if current and not previous else 0
        return super().massive_value(kind, args, player)

    # --------------------------------------------------------------- actions
    def massive_action(self, kind: str, args: dict[str, Any], player: int) -> bool:
        if kind in {"Suppress Native Win/Loss", "Enable Trigger-Controlled Results", "Blank Map Bootstrap"}:
            self._mission131_enable_trigger_results(restore_bridge=True)
            if kind == "Blank Map Bootstrap" and bool(args.get("message", True)):
                self._game_message({
                    "text": str(args.get("text", "Trigger-controlled scenario initialized.")),
                    "color": str(args.get("color", "White — native highlight")),
                    "recipients": str(args.get("recipients", "All active players")),
                    "seconds": max(1, int(args.get("seconds", 4))),
                    "also_log": False,
                }, player)
            return True
        if kind in {"Restore Native Win/Loss", "Disable Trigger-Controlled Results"}:
            self._mission131_disable_trigger_results()
            return True
        if kind == "List TTS Voices":
            voices = self._mission131_tts_voices(refresh=bool(args.get("refresh", True)))
            if not voices:
                self.log("TTS VOICES: none available through Windows System.Speech")
            else:
                self.log("TTS VOICES: " + " | ".join(f"{v['Name']} [{v['Gender']}, {v['Culture']}]" for v in voices))
            return True
        if kind in {"Scene Actor TTS", "Scene Narrator TTS"}:
            return self._mission131_tts_action(kind, args, player)
        if kind == "Scene Wait For TTS":
            self._mission131_cleanup_tts(done_only=True)
            if any(proc.poll() is None for proc in self._mission131_tts_processes):
                raise ActionDeferred("Waiting for active TTS speech", retry_after=0.10)
            return True
        if kind == "Scene Wait For Local Key":
            vk = self._mission131_vk(args.get("key", "Space"))
            state = self._cached_action_value(
                "mission131_wait_key",
                lambda: {"started": time.monotonic(), "previous": self._mission131_key_state(vk)},
            )
            current = self._mission131_key_state(vk)
            pressed = bool(current and not bool(state.get("previous", False)))
            state["previous"] = current
            if pressed:
                variable = str(args.get("set_variable", "")).strip()
                if variable:
                    self.variables[variable] = int(args.get("value", 1))
                return True
            timeout = max(0.0, float(args.get("timeout", 0.0)))
            if timeout and time.monotonic() - float(state["started"]) >= timeout:
                if str(args.get("on_timeout", "Continue")) == "Error":
                    raise RuntimeError(f"Scene Wait For Local Key timed out waiting for {args.get('key','Space')}")
                return True
            raise ActionDeferred(f"Waiting for local key {args.get('key','Space')}", retry_after=0.05)
        if kind == "Scene Choice":
            prompt = str(args.get("prompt", "Choose:")).strip() or "Choose:"
            raw_options = [str(args.get(f"option{i}", "")).strip() for i in range(1, 5)]
            options = [(i, text) for i, text in enumerate(raw_options, 1) if text]
            if len(options) < 2:
                raise ValueError("Scene Choice requires at least option1 and option2")
            variable = str(args.get("variable", "Choice")).strip() or "Choice"

            def start_choice() -> dict[str, Any]:
                lines = [prompt] + [f"[{i}] {text}" for i, text in options]
                self._game_message({
                    "text": "\n".join(lines),
                    "color": str(args.get("color", "White — native highlight")),
                    "recipients": str(args.get("recipients", "All active players")),
                    "seconds": max(1, int(args.get("seconds", 12))),
                    "also_log": bool(args.get("also_log", True)),
                }, player)
                proc = None
                if bool(args.get("tts", False)):
                    spoken = prompt + ". " + ". ".join(f"Option {i}: {text}" for i, text in options)
                    proc = self._mission131_tts_spawn(
                        text=spoken,
                        gender=str(args.get("gender", "Auto")),
                        voice_name=str(args.get("voice_name", "")),
                        rate=int(args.get("rate", 0)),
                        volume=int(args.get("volume", 100)),
                    )
                return {
                    "started": time.monotonic(),
                    "previous": {i: self._mission131_key_state(self._mission131_vk(str(i))) for i, _ in options},
                    "tts_proc": proc,
                }

            state = self._cached_action_value("mission131_scene_choice", start_choice)
            for i, _text in options:
                vk = self._mission131_vk(str(i))
                current = self._mission131_key_state(vk)
                previous = bool(state["previous"].get(i, False))
                state["previous"][i] = current
                if current and not previous:
                    self.variables[variable] = i
                    text_var = str(args.get("text_variable", "")).strip()
                    if text_var:
                        # Variables are normally numeric; put the selected option index
                        # there too and log the authored text for deterministic branching.
                        self.variables[text_var] = i
                    self.log(f"SCENE CHOICE v1.31: {variable}={i} ({dict(options)[i]})")
                    return True
            timeout = max(0.0, float(args.get("timeout", 0.0)))
            if timeout and time.monotonic() - float(state["started"]) >= timeout:
                default_choice = int(args.get("default_choice", 0))
                valid = {i for i, _ in options}
                if default_choice in valid:
                    self.variables[variable] = default_choice
                    self.log(f"SCENE CHOICE TIMEOUT v1.31: {variable}={default_choice} (default)")
                    return True
                if str(args.get("on_timeout", "Continue")) == "Error":
                    raise RuntimeError("Scene Choice timed out without a valid default choice")
                return True
            raise ActionDeferred("Waiting for local scene choice (number key)", retry_after=0.05)
        if kind == "Stop TTS":
            self._mission131_cleanup_tts(done_only=False)
            self.log("TTS STOP: all Trigger Studio speech processes stopped")
            return True
        return super().massive_action(kind, args, player)
