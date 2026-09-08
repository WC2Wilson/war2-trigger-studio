from __future__ import annotations

from dataclasses import dataclass
import random
import time
from typing import Any, Protocol

from trigger_model import Clause, Scenario, Trigger


class FunctionReturn(RuntimeError):
    """Stops a synchronous trigger-function call without logging an action error."""


class ActionDeferred(RuntimeError):
    """A live action is still running and should be retried on a later cycle."""

    def __init__(self, message: str, retry_after: float = 0.25):
        super().__init__(message)
        self.retry_after = max(0.05, float(retry_after))


class GameAdapter(Protocol):
    def value(self, kind: str, args: dict[str, Any], player: int) -> Any: ...
    def action(self, kind: str, args: dict[str, Any], player: int) -> None: ...


def compare(actual: int, op: str, expected: int) -> bool:
    return {
        "At least": actual >= expected,
        "At most": actual <= expected,
        "Exactly": actual == expected,
        "Not equal": actual != expected,
    }.get(op, False)


@dataclass
class _PendingActions:
    trigger_index: int
    player: int
    next_action: int
    due_at: float


class TriggerEngine:
    """StarCraft-style trigger evaluator with non-blocking action scheduling.

    Wait and Random Wait are runtime scheduler operations, never sleeps. Trigger
    control actions are handled here so they cannot interfere with Warcraft's
    simulation-thread dispatcher. All native gameplay actions remain delegated to
    LiveAdapter.
    """

    def __init__(self, scenario: Scenario, adapter: GameAdapter):
        self.scenario = scenario
        self.adapter = adapter
        setattr(self.adapter, "engine", self)
        self.completed: set[tuple[int, int]] = set()
        self.pending: dict[tuple[int, int], _PendingActions] = {}
        self.run_counts: dict[tuple[int, int], int] = {}
        self.last_fired: dict[tuple[int, int], float] = {}
        self.started = time.monotonic()
        self.history: list[dict[str, Any]] = []
        self.condition_failures: dict[tuple[int, int], list[str]] = {}
        self._stop_cycle_requested = False
        self._call_stack: list[int] = []
        self._rng = random.Random(time.time_ns())
        self.paused = False

    def find_trigger_index(self, name: str) -> int | None:
        folded = str(name).strip().casefold()
        for index, trigger in enumerate(self.scenario.triggers):
            if trigger.name.strip().casefold() == folded:
                return index
        return None

    def find_trigger(self, name: str) -> Trigger | None:
        index = self.find_trigger_index(name)
        return self.scenario.triggers[index] if index is not None else None

    def _log(self, text: str) -> None:
        logger = getattr(self.adapter, "log", None)
        if logger:
            logger(text)

    def condition(self, clause: Clause, player: int) -> bool:
        if clause.kind == "Always":
            result = True
        elif clause.kind == "Never":
            result = False
        else:
            actual = self.adapter.value(clause.kind, clause.args, player)
            if clause.kind in {"Switch", "Game State", "Player Status", "Trigger Enabled", "Objective State", "Auto Spellcasting", "Wave Director State", "Quest State", "Squad Controller State", "Reinforcement Director State", "Vote State", "Source Production State", "Source Worker Cargo Type", "Campaign Objective State", "Cutscene State", "Scene Actor State", "Campaign UI Capability", "Cutscene Input Lock State", "Native Win/Loss Suppressed", "Blank Map Guard Armed", "TTS Available", "TTS Speaking"}:
                result = actual == clause.args.get("state")
            else:
                result = compare(
                    int(actual),
                    clause.args.get("comparison", "At least"),
                    int(clause.args.get("amount", 0)),
                )
        if bool(clause.args.get("negate", False)):
            result = not result
        return result

    def _conditions_pass(self, trigger_index: int, player: int) -> bool:
        trigger = self.scenario.triggers[trigger_index]
        results: list[bool] = []
        failures: list[str] = []
        for clause in trigger.conditions:
            try:
                passed = self.condition(clause, player)
            except Exception as exc:
                passed = False
                failures.append(f"{clause.kind}: {exc}")
            else:
                if not passed:
                    failures.append(clause.kind)
            results.append(passed)
        mode = str(getattr(trigger, "condition_mode", "All"))
        passed = any(results) if mode == "Any" else all(results)
        key = (trigger_index, player)
        if passed:
            self.condition_failures.pop(key, None)
        else:
            self.condition_failures[key] = failures
        return passed

    @staticmethod
    def _wait_seconds(clause: Clause, rng: random.Random) -> float:
        if clause.kind == "Random Wait":
            low = max(0.0, float(clause.args.get("minimum", 0)))
            high = max(0.0, float(clause.args.get("maximum", low)))
            if low > high:
                low, high = high, low
            return rng.uniform(low, high)
        raw = clause.args.get("seconds", clause.args.get("ticks", 0))
        return max(0.0, float(raw))

    def _mark_finished(self, key: tuple[int, int], trigger: Trigger) -> None:
        runs = self.run_counts.get(key, 0)
        max_runs = max(0, int(trigger.max_runs))
        if not trigger.preserved or (max_runs and runs >= max_runs):
            self.completed.add(key)

    def reset_trigger(self, trigger_index: int, player: int | None = None) -> None:
        players = range(16) if player is None else (player,)
        for current_player in players:
            key = (trigger_index, current_player)
            self.completed.discard(key)
            self.pending.pop(key, None)
            self.run_counts.pop(key, None)
            self.last_fired.pop(key, None)
            self.condition_failures.pop(key, None)

    def _control_action(self, action: Clause, trigger_index: int, player: int, now: float) -> str | None:
        kind, args = action.kind, action.args
        if kind not in {
            "Enable Trigger", "Disable Trigger", "Toggle Trigger", "Reset Trigger",
            "Run Trigger", "Stop Trigger Actions", "Stop Trigger Cycle", "Breakpoint",
        }:
            return None
        if kind == "Stop Trigger Actions":
            self._log(f"TRIGGER FLOW: stopped remaining actions in {self.scenario.triggers[trigger_index].name}")
            return "stop"
        if kind == "Stop Trigger Cycle":
            self._stop_cycle_requested = True
            self._log("TRIGGER FLOW: stopped remaining triggers for this engine cycle")
            return "stop"
        if kind == "Breakpoint":
            self.paused = True
            self._stop_cycle_requested = True
            self._log(f"BREAKPOINT: {args.get('message', 'Paused by trigger breakpoint')}")
            return "stop"
        target_name = str(args.get("trigger", "")).strip()
        target_index = self.find_trigger_index(target_name)
        if target_index is None:
            raise ValueError(f"Unknown trigger: {target_name}")
        target = self.scenario.triggers[target_index]
        if kind == "Enable Trigger":
            target.enabled = True
            self._log(f"TRIGGER CONTROL: enabled {target.name}")
        elif kind == "Disable Trigger":
            target.enabled = False
            self._log(f"TRIGGER CONTROL: disabled {target.name}")
        elif kind == "Toggle Trigger":
            target.enabled = not target.enabled
            self._log(f"TRIGGER CONTROL: {target.name} -> {'enabled' if target.enabled else 'disabled'}")
        elif kind == "Reset Trigger":
            reset_player = player if bool(args.get("current_player_only", False)) else None
            self.reset_trigger(target_index, reset_player)
            self._log(f"TRIGGER CONTROL: reset {target.name}")
        elif kind == "Run Trigger":
            if target_index in self._call_stack:
                chain = " -> ".join(self.scenario.triggers[i].name for i in self._call_stack + [target_index])
                raise RuntimeError(f"Recursive Run Trigger call blocked: {chain}")
            self._call_stack.append(target_index)
            try:
                self._execute_actions(target_index, player, 0, now, called=True)
            finally:
                self._call_stack.pop()
            self._log(f"TRIGGER CONTROL: called {target.name} for Player {player + 1}")
        return "continue"

    def _execute_actions(
        self,
        trigger_index: int,
        player: int,
        start_action: int,
        now: float,
        called: bool = False,
    ) -> bool:
        """Run actions until completion or a non-blocking wait."""
        trigger = self.scenario.triggers[trigger_index]
        key = (trigger_index, player)
        action_index = start_action
        while action_index < len(trigger.actions):
            action = trigger.actions[action_index]
            if action.kind in {"Wait", "Random Wait"}:
                seconds = self._wait_seconds(action, self._rng)
                action_index += 1
                if seconds > 0:
                    self.pending[key] = _PendingActions(trigger_index, player, action_index, now + seconds)
                    self._log(f"TRIGGER WAIT: {trigger.name} paused {seconds:.2f}s at action {action_index}")
                    return False
                continue
            try:
                control = self._control_action(action, trigger_index, player, now)
            except Exception as exc:
                self._log(
                    f"ACTION ERROR: {trigger.name} [Player {player + 1}] action {action_index + 1} "
                    f"({action.kind}): {exc}; action skipped, runtime continues"
                )
                action_index += 1
                continue
            if control == "stop":
                self.pending.pop(key, None)
                return True
            if control == "continue":
                action_index += 1
                continue

            set_context = getattr(self.adapter, "set_action_context", None)
            finish_context = getattr(self.adapter, "finish_action_context", None)
            context_token = (trigger_index, player, self.run_counts.get(key, 0), action_index)
            if set_context:
                set_context(context_token)
            keep_context = False
            try:
                self.adapter.action(action.kind, action.args, player)
            except FunctionReturn:
                self.pending.pop(key, None)
                return True
            except ActionDeferred as exc:
                keep_context = True
                self.pending[key] = _PendingActions(trigger_index, player, action_index, now + exc.retry_after)
                return False
            except Exception as exc:
                self._log(
                    f"ACTION ERROR: {trigger.name} [Player {player + 1}] action {action_index + 1} "
                    f"({action.kind}): {exc}; action skipped, runtime continues"
                )
            finally:
                if finish_context:
                    finish_context(context_token, keep_for_retry=keep_context)
                elif set_context:
                    set_context(None)
            action_index += 1
        self.pending.pop(key, None)
        return True

    def _resume_pending(self, now: float) -> None:
        for key, item in list(self.pending.items()):
            if item.due_at > now:
                continue
            if not (0 <= item.trigger_index < len(self.scenario.triggers)):
                self.pending.pop(key, None)
                continue
            trigger = self.scenario.triggers[item.trigger_index]
            finished = self._execute_actions(item.trigger_index, item.player, item.next_action, now)
            if finished:
                self._mark_finished(key, trigger)

    def continue_execution(self) -> None:
        self.paused = False
        self._log("TRIGGER DEBUGGER: continued")

    def step_once(self) -> list[str]:
        was_paused = self.paused
        self.paused = False
        try:
            return self.cycle(force=True)
        finally:
            self.paused = True if was_paused else self.paused

    def cycle(self, force: bool = False) -> list[str]:
        if self.paused and not force:
            return []
        fired: list[str] = []
        self._stop_cycle_requested = False
        prepare = getattr(self.adapter, "prepare_cycle", None)
        if prepare:
            prepared = prepare()
            # Maintenance systems such as automatic spellcasting may publish a
            # simulation-thread command outside a trigger action.  Do not let a
            # normal trigger action compete for the same mailbox until that
            # maintenance command has completed and been consumed.
            if prepared is False:
                return []

        now = time.monotonic()
        self._resume_pending(now)

        for index, trigger in enumerate(self.scenario.triggers):
            if self._stop_cycle_requested:
                break
            if not trigger.enabled:
                continue
            for player in trigger.players:
                if self._stop_cycle_requested:
                    break
                key = (index, player)
                if key in self.pending or key in self.completed:
                    continue
                if now - self.started < max(0.0, float(trigger.start_delay)):
                    continue

                runs = self.run_counts.get(key, 0)
                max_runs = max(0, int(trigger.max_runs))
                if max_runs and runs >= max_runs:
                    self.completed.add(key)
                    continue

                if trigger.preserved and key in self.last_fired:
                    interval = max(0.0, float(trigger.repeat_interval))
                    if now - self.last_fired[key] < interval:
                        continue

                if not self._conditions_pass(index, player):
                    continue

                self.last_fired[key] = now
                self.run_counts[key] = runs + 1
                started_at = time.perf_counter()
                finished = self._execute_actions(index, player, 0, now)
                elapsed_ms = (time.perf_counter() - started_at) * 1000.0
                fired.append(f"{trigger.name} [Player {player + 1}]")
                self.history.append({
                    "time": now,
                    "trigger": trigger.name,
                    "player": player,
                    "run": runs + 1,
                    "duration_ms": elapsed_ms,
                    "completed": finished,
                })
                if len(self.history) > 2000:
                    del self.history[:500]
                if finished:
                    self._mark_finished(key, trigger)
        return fired

    def diagnostic_report(self) -> list[str]:
        lines = ["TRIGGER ENGINE STATE"]
        for index, trigger in enumerate(self.scenario.triggers):
            status = "enabled" if trigger.enabled else "disabled"
            lines.append(f"{index + 1:03d}. {trigger.name}: {status}, mode={trigger.condition_mode}")
            for player in trigger.players:
                key = (index, player)
                runs = self.run_counts.get(key, 0)
                state = "pending" if key in self.pending else "complete" if key in self.completed else "ready"
                failures = ", ".join(self.condition_failures.get(key, []))
                lines.append(f"     P{player + 1}: runs={runs}, {state}" + (f", false: {failures}" if failures else ""))
        return lines
