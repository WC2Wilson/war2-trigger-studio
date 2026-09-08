from __future__ import annotations

from dataclasses import dataclass
import ast
import math
import random
import time
from typing import Any

MASSIVE_UNHANDLED = object()

ORDER_ACTIONS = {
    "Idle": {2, 60},
    "Move": {3},
    "Attack": {8, 9, 10, 11, 12},
    "Patrol": {11},
    "Cast Spell": set(range(39, 60)),
    "Dying": {0, 1},
}

STATUS_OFFSETS = {
    "Invisibility": (0x44, "word", 2000),
    "Unholy Armor": (0x46, "word", 500),
    "Bloodlust": (0x48, "word", 1000),
    "Haste": (0x4A, "sword", 1000),
    "Slow": (0x4A, "sword", -1000),
    "Flame Shield": (0x4E, "word", 500),
}

STAT_RVAS = {
    "Deaths Men": 0x519438,
    "Deaths Buildings": 0x519458,
    "Kills Men": 0x519478,
    "Kills Buildings": 0x519498,
    "Score": 0x5193A8,
}

UNIT_HP_TABLE_RVA = 0x5177C0


@dataclass
class CountdownState:
    duration: float = 0.0
    remaining: float = 0.0
    end_at: float = 0.0
    running: bool = False
    ever_started: bool = False

    def value(self, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        if self.running:
            return max(0.0, self.end_at - now)
        return max(0.0, self.remaining)

    def sync(self, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        value = self.value(now)
        if self.running and value <= 0:
            self.running = False
            self.remaining = 0.0
        elif self.running:
            self.remaining = value
        return value


class MassiveFeatureMixin:
    """Large, self-contained trigger layer added without changing WT30 vision.

    The mixin deliberately uses already validated LiveAdapter primitives for all
    native mutations. It owns only high-level trigger state, event snapshots,
    dynamic locations, arithmetic, timers, objectives, and native-verified unit
    fields whose offsets are already decoded by the base runtime.
    """

    def _init_massive_features(self) -> None:
        scenario = getattr(self, "scenario", None)
        self.variables: dict[str, Any] = dict(getattr(scenario, "variables", {}) or {})
        self.countdown_timers: dict[str, CountdownState] = {
            str(name): CountdownState(float(seconds), float(seconds))
            for name, seconds in dict(getattr(scenario, "timers", {}) or {}).items()
        }
        self.objectives: dict[str, str] = dict(getattr(scenario, "objectives", {}) or {})
        self.completed_objectives: set[str] = set()
        self._follow_locations: dict[str, dict[str, Any]] = {}
        self._location_entered_at: dict[tuple[tuple[int, int], str], float] = {}
        self._left_location_events: dict[str, set[tuple[int, int]]] = {}
        self._entered_location_events: dict[str, set[tuple[int, int]]] = {}
        self._unit_damage_events: dict[tuple[int, int], int] = {}
        self._unit_heal_events: dict[tuple[int, int], int] = {}
        self._unit_attack_events: set[tuple[int, int]] = set()
        self._switch_changes: dict[str, tuple[Any, Any]] = {}
        self._counter_changes: dict[str, tuple[int, int]] = {}
        self._variable_changes: dict[str, tuple[Any, Any]] = {}
        self._last_seen_switches: dict[str, Any] = dict(getattr(self, "switches", {}))
        self._last_seen_counters: dict[str, int] = dict(getattr(self, "counters", {}))
        self._last_seen_variables: dict[str, Any] = dict(self.variables)
        self.unit_groups: dict[str, set[tuple[int, int]]] = {}
        self._event_context: dict[str, Any] = {}
        self._available_events: set[str] = set()
        self._massive_rng = random.Random()
        self._massive_rng.seed(time.time_ns())
        self.auto_spellcasting: dict[int, dict[str, Any]] = {}
        self._auto_spell_cooldowns: dict[tuple[int, int], float] = {}
        self._auto_spell_rotation: dict[tuple[int, int], int] = {}
        self._auto_spell_next_cycle = 0.0
        self._auto_spell_action_cache: dict[tuple[int, ...], tuple[list[tuple], list[dict[str, Any]], list[tuple[tuple[int, int], float]], float]] = {}
        # Caster keys protected from generic attack-route maintenance while a
        # native spell order is pending or executing.  Unit-target spell actions
        # keep a raw PTUnit pointer at Unit+0x88; replacing that order can clear
        # the pointer inside the native spell function and crash Warcraft.
        self._auto_spell_route_guards: set[tuple[int, int]] = set()
        # Auto-casters are parked on a target-less native Move-to-current-tile
        # order before any unit-target spell is queued. This prevents a saved
        # Attack Location action from replacing Unit+0x88 during spell execution.
        self._auto_spell_parking: set[tuple[int, int]] = set()
        # Time each selected caster entered the one-cast parking stage. A caster
        # that cannot settle because combat keeps retargeting it is released
        # quickly instead of being stranded outside the battle.
        self._auto_spell_parking_started: dict[tuple[int, int], float] = {}

    def _massive_begin_run(self) -> None:
        scenario = getattr(self, "scenario", None)
        self.variables = dict(getattr(scenario, "variables", {}) or {})
        self.countdown_timers = {
            str(name): CountdownState(float(seconds), float(seconds))
            for name, seconds in dict(getattr(scenario, "timers", {}) or {}).items()
        }
        self.objectives = dict(getattr(scenario, "objectives", {}) or {})
        self.completed_objectives.clear()
        self._follow_locations.clear()
        self._location_entered_at.clear()
        self._left_location_events.clear()
        self._entered_location_events.clear()
        self._unit_damage_events.clear()
        self._unit_heal_events.clear()
        self._unit_attack_events.clear()
        self._switch_changes.clear()
        self._counter_changes.clear()
        self._variable_changes.clear()
        self._last_seen_switches = dict(getattr(self, "switches", {}))
        self._last_seen_counters = dict(getattr(self, "counters", {}))
        self._last_seen_variables = dict(self.variables)
        self.unit_groups.clear()
        self._event_context.clear()
        self._available_events.clear()
        self.auto_spellcasting.clear()
        self._auto_spell_cooldowns.clear()
        self._auto_spell_rotation.clear()
        self._auto_spell_next_cycle = 0.0
        self._auto_spell_action_cache.clear()
        self._auto_spell_route_guards.clear()
        self._auto_spell_parking.clear()
        self._auto_spell_parking_started.clear()

    # ------------------------------------------------------------------ helpers
    def _find_location(self, name: str):
        scenario = getattr(self, "scenario", None)
        if not scenario:
            raise ValueError("This action requires an active trigger scenario")
        location = next((loc for loc in scenario.locations if loc.name == name), None)
        if location is None:
            raise ValueError(f"Unknown location: {name}")
        return location

    @staticmethod
    def _inside(unit: Any, location: Any) -> bool:
        return (
            int(location.left) <= int(unit.x) <= int(location.right)
            and int(location.top) <= int(unit.y) <= int(location.bottom)
        )

    @staticmethod
    def _unit_key_massive(unit: Any) -> tuple[int, int]:
        return (int(unit.address), int(getattr(unit, "token", 0)))

    @staticmethod
    def _selector_matches(unit: Any, args: dict[str, Any], executing_player: int) -> bool:
        owner = int(args.get("player", executing_player))
        requested = args.get("unit", "Any")
        if owner >= 0 and int(unit.owner) != owner:
            return False
        if requested != "Any" and int(unit.unit_type) != int(requested):
            return False
        return True

    def _timer(self, name: Any, create: bool = True) -> CountdownState:
        key = str(name or "Timer 1").strip()
        if not key:
            raise ValueError("Timer name cannot be blank")
        timer = self.countdown_timers.get(key)
        if timer is None and create:
            timer = CountdownState()
            self.countdown_timers[key] = timer
        if timer is None:
            return CountdownState()
        timer.sync()
        return timer

    def _numeric_variable(self, name: Any) -> int:
        key = str(name or "Variable 1").strip()
        value = self.variables.get(key, 0)
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Variable {key!r} is not numeric: {value!r}") from exc

    def _set_variable(self, name: Any, value: Any) -> None:
        key = str(name or "Variable 1").strip()
        if not key:
            raise ValueError("Variable name cannot be blank")
        self.variables[key] = value

    def _resolve_point(self, args: dict[str, Any], location_key: str = "source_location") -> tuple[int, int]:
        name = str(args.get(location_key, "Anywhere"))
        if name != "Anywhere":
            loc = self._find_location(name)
            return ((int(loc.left) + int(loc.right)) // 2, (int(loc.top) + int(loc.bottom)) // 2)
        return int(args.get("x", 0)), int(args.get("y", 0))

    def _max_hp(self, unit: Any) -> int:
        return max(1, int(self.pm.read_ushort(self.base + UNIT_HP_TABLE_RVA + int(unit.unit_type) * 2)))

    def _write_status(self, unit: Any, status: str, ticks: int) -> None:
        offset, kind, default = STATUS_OFFSETS[status]
        value = int(default if ticks <= 0 else ticks)
        # Slow and Haste have signed direction baked into their vanilla default.
        if status == "Slow":
            value = -abs(value)
        elif status == "Haste":
            value = abs(value)
        if kind == "sword":
            value = max(-32768, min(32767, value))
            self.pm.write_bytes(unit.address + offset, int(value).to_bytes(2, "little", signed=True), 2)
        else:
            value = max(0, min(65535, value))
            self.pm.write_ushort(unit.address + offset, value)

    def _remove_one_unit_safely(self, unit: Any) -> None:
        if int(unit.sflags) & 0x0008:
            raise RuntimeError("Replace Units will not remove hidden/cargo units")
        key = self._unit_key(unit)
        calls = [
            (self.remove_callees["cancel_tree_harvest"], [unit.address]),
            (self.remove_callees["unplace_man"], [unit.address]),
            (self.remove_callees["deselect_unit"], [unit.address]),
            (self.remove_callees["strategy_alert_kill"], [unit.address]),
            (self.remove_callees["count_remove"], [unit.address]),
            (self.unit_free_address, [unit.address]),
        ]
        self._call_cdecl_sequence(calls)
        after = self.pm.read_ushort(unit.address + 0x1E)
        if not after & 0x0001:
            raise RuntimeError("Warcraft rejected the old-unit cleanup during Replace Units")
        self._pending_removed_keys.add(key)


    def _set_event_context(self, event_type: str, unit: Any | None = None, amount: int = 0, previous: Any | None = None) -> None:
        context: dict[str, Any] = {
            "event_type": str(event_type),
            "amount": int(amount),
        }
        source = unit if unit is not None else previous
        if source is not None:
            context.update({
                "key": self._unit_key_massive(source),
                "address": int(source.address),
                "player": int(source.owner),
                "unit_type": int(source.unit_type),
                "x": int(source.x),
                "y": int(source.y),
                "health": int(source.health),
                "mana": int(getattr(source, "mana", 0)),
            })
        self._event_context = context
        self._available_events.add(str(event_type))

    def _event_unit(self) -> Any | None:
        key = self._event_context.get("key")
        if key is None:
            return None
        for source in (getattr(self, "_snapshot", {}), getattr(self, "_previous_snapshot", {})):
            unit = source.get(tuple(key))
            if unit is not None:
                return unit
        return None

    def _prime_event_context(self, event_type: str) -> bool:
        current = getattr(self, "_snapshot", {})
        previous = getattr(self, "_previous_snapshot", {})
        if event_type == "Unit Created" and getattr(self, "created_units", []):
            self._set_event_context(event_type, self.created_units[0], len(self.created_units)); return True
        if event_type == "Unit Died" and getattr(self, "died_units", []):
            self._set_event_context(event_type, self.died_units[0], len(self.died_units), self.died_units[0]); return True
        if event_type == "Unit Removed" and getattr(self, "removed_units", []):
            self._set_event_context(event_type, self.removed_units[0], len(self.removed_units), self.removed_units[0]); return True
        if event_type in {"Unit Damaged", "Unit Healed", "Unit Under Attack"}:
            keys = self._unit_damage_events if event_type == "Unit Damaged" else self._unit_heal_events if event_type == "Unit Healed" else self._unit_attack_events
            if keys:
                key = next(iter(keys))
                unit = current.get(key)
                if unit is not None:
                    amount = int(keys.get(key, 1)) if isinstance(keys, dict) else 1
                    self._set_event_context(event_type, unit, amount); return True
        if event_type in {"Unit Entered Location", "Unit Left Location"}:
            table = self._entered_location_events if event_type == "Unit Entered Location" else self._left_location_events
            source = current if event_type == "Unit Entered Location" else previous
            for location_name, keys in table.items():
                if keys:
                    key = next(iter(keys)); unit = source.get(key)
                    if unit is not None:
                        self._set_event_context(event_type, unit, 1, unit)
                        self._event_context["location"] = location_name
                        return True
        return False

    def _group_units(self, name: Any) -> list[Any]:
        key = str(name or "Unit Group 1").strip()
        wanted = self.unit_groups.get(key, set())
        if not wanted:
            return []
        world = {self._unit_key_massive(unit): unit for unit in self.units()}
        live = [world[item] for item in wanted if item in world]
        self.unit_groups[key] = {self._unit_key_massive(unit) for unit in live}
        return sorted(live, key=lambda unit: int(unit.address))

    def _evaluate_expression(self, expression: Any, player: int) -> int | float:
        text = str(expression or "0").strip()
        if not text:
            return 0
        if len(text) > 512:
            raise ValueError("Expression is limited to 512 characters")
        try:
            tree = ast.parse(text, mode="eval")
        except SyntaxError as exc:
            raise ValueError(f"Invalid expression: {exc.msg}") from exc
        if sum(1 for _ in ast.walk(tree)) > 128:
            raise ValueError("Expression is too complex")

        def scalar(value: Any) -> int | float:
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, (int, float)):
                return value
            raise ValueError(f"Expression produced a non-numeric value: {value!r}")

        def evaluate(node: ast.AST) -> Any:
            if isinstance(node, ast.Expression):
                return evaluate(node.body)
            if isinstance(node, ast.Constant):
                if isinstance(node.value, (int, float, str, bool)):
                    return node.value
                raise ValueError("Only numbers and quoted names are allowed in expressions")
            if isinstance(node, ast.Name):
                values = {
                    "player": player + 1,
                    "elapsed": int(time.monotonic() - self.started),
                    "map_width": int(self.map_width),
                    "map_height": int(self.map_height),
                    "event_damage": int(self._event_context.get("amount", 0)),
                    "event_player": int(self._event_context.get("player", -1)) + 1,
                    "event_unit": int(self._event_context.get("unit_type", -1)),
                    "event_x": int(self._event_context.get("x", 0)),
                    "event_y": int(self._event_context.get("y", 0)),
                }
                if node.id not in values:
                    raise ValueError(f"Unknown expression name: {node.id}")
                return values[node.id]
            if isinstance(node, ast.UnaryOp):
                value = scalar(evaluate(node.operand))
                if isinstance(node.op, ast.USub): return -value
                if isinstance(node.op, ast.UAdd): return value
                if isinstance(node.op, ast.Not): return int(not value)
                raise ValueError("Unsupported unary operator")
            if isinstance(node, ast.BinOp):
                left, right = scalar(evaluate(node.left)), scalar(evaluate(node.right))
                if isinstance(node.op, ast.Add): return left + right
                if isinstance(node.op, ast.Sub): return left - right
                if isinstance(node.op, ast.Mult): return left * right
                if isinstance(node.op, ast.Div):
                    if right == 0: raise ValueError("Expression division by zero")
                    return left / right
                if isinstance(node.op, ast.FloorDiv):
                    if right == 0: raise ValueError("Expression division by zero")
                    return left // right
                if isinstance(node.op, ast.Mod):
                    if right == 0: raise ValueError("Expression modulo by zero")
                    return left % right
                if isinstance(node.op, ast.Pow):
                    if abs(right) > 10: raise ValueError("Expression exponent is too large")
                    return left ** right
                raise ValueError("Unsupported binary operator")
            if isinstance(node, ast.BoolOp):
                values = [bool(scalar(evaluate(item))) for item in node.values]
                return int(all(values) if isinstance(node.op, ast.And) else any(values))
            if isinstance(node, ast.Compare):
                left = evaluate(node.left)
                result = True
                for operator, comparator in zip(node.ops, node.comparators):
                    right = evaluate(comparator)
                    if isinstance(operator, ast.Eq): ok = left == right
                    elif isinstance(operator, ast.NotEq): ok = left != right
                    elif isinstance(operator, ast.Lt): ok = scalar(left) < scalar(right)
                    elif isinstance(operator, ast.LtE): ok = scalar(left) <= scalar(right)
                    elif isinstance(operator, ast.Gt): ok = scalar(left) > scalar(right)
                    elif isinstance(operator, ast.GtE): ok = scalar(left) >= scalar(right)
                    else: raise ValueError("Unsupported comparison operator")
                    result = result and ok
                    left = right
                return int(result)
            if isinstance(node, ast.IfExp):
                return evaluate(node.body if bool(scalar(evaluate(node.test))) else node.orelse)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                name = node.func.id
                args = [evaluate(arg) for arg in node.args]
                if name == "var": return self._numeric_variable(args[0] if args else "Variable 1")
                if name == "counter": return int(self.counters.get(str(args[0] if args else "Counter 1"), 0))
                if name == "timer": return self._timer(args[0] if args else "Timer 1").value()
                if name == "group": return len(self._group_units(args[0] if args else "Unit Group 1"))
                if name == "event": return self._event_context.get(str(args[0] if args else "amount"), 0)
                numeric = [scalar(value) for value in args]
                if name == "rand":
                    if len(numeric) != 2: raise ValueError("rand requires two arguments")
                    low, high = int(numeric[0]), int(numeric[1])
                    if low > high: low, high = high, low
                    return self._massive_rng.randint(low, high)
                if name == "clamp":
                    if len(numeric) != 3: raise ValueError("clamp requires three arguments")
                    return max(numeric[1], min(numeric[2], numeric[0]))
                if name == "min":
                    if not numeric: raise ValueError("min requires at least one argument")
                    return min(numeric)
                if name == "max":
                    if not numeric: raise ValueError("max requires at least one argument")
                    return max(numeric)
                if name in {"abs", "round", "int", "ceil", "floor"} and len(numeric) != 1:
                    raise ValueError(f"{name} requires one argument")
                if name == "abs": return abs(numeric[0])
                if name == "round": return round(numeric[0])
                if name == "int": return int(numeric[0])
                if name == "ceil": return math.ceil(numeric[0])
                if name == "floor": return math.floor(numeric[0])
                raise ValueError(f"Unknown expression function: {name}")
            raise ValueError(f"Unsupported expression element: {type(node).__name__}")

        result = evaluate(tree)
        return scalar(result)

    def _exact_group_order(self, units: list[Any], order: str, x: int, y: int) -> int:
        order = str(order).title()
        callback = {"Move": "do_move", "Attack": "do_attack", "Patrol": "do_patrol"}.get(order)
        if callback is None:
            raise ValueError(f"Unsupported group order: {order}")
        eligible = [unit for unit in units if int(unit.unit_type) < 58 and not (int(unit.sflags) & 0x0008)]
        if len(eligible) != len(units):
            raise RuntimeError("Named unit-group orders support visible mobile units only")
        self._call_cdecl_batched([
            (self.order_callees["set_target"], [unit.address, int(x), int(y), 0, self.order_callees[callback]])
            for unit in eligible
        ])
        if order == "Attack":
            for unit in eligible:
                self._attack_routes[self._unit_key(unit)] = (int(x), int(y))
        return len(eligible)

    def _formation_points(self, amount: int, center_x: int, center_y: int, formation: str, spacing: int, bounds: Any | None = None) -> list[tuple[int, int]]:
        formation = str(formation or "Compact")
        spacing = max(1, int(spacing))
        points: list[tuple[int, int]] = []
        if formation == "Horizontal line":
            start = center_x - ((amount - 1) * spacing) // 2
            points = [(start + index * spacing, center_y) for index in range(amount)]
        elif formation == "Vertical line":
            start = center_y - ((amount - 1) * spacing) // 2
            points = [(center_x, start + index * spacing) for index in range(amount)]
        elif formation == "Grid":
            width = max(1, int(math.ceil(math.sqrt(amount))))
            rows = int(math.ceil(amount / width))
            start_x = center_x - ((width - 1) * spacing) // 2
            start_y = center_y - ((rows - 1) * spacing) // 2
            points = [(start_x + (index % width) * spacing, start_y + (index // width) * spacing) for index in range(amount)]
        elif formation == "Random in spawn location" and bounds is not None:
            points = [
                (self._massive_rng.randint(int(bounds.left), int(bounds.right)), self._massive_rng.randint(int(bounds.top), int(bounds.bottom)))
                for _ in range(amount)
            ]
        else:
            points = [(center_x, center_y)] * amount
        return [
            (max(0, min(self.map_width - 1, int(x))), max(0, min(self.map_height - 1, int(y))))
            for x, y in points
        ]

    # ---------------------------------------------------------- cycle integration
    def _massive_prepare_pre(self, world: list[Any]) -> bool:
        # Dynamic locations follow the first matching live unit. This happens
        # before normal conditions evaluate, matching StarCraft Move Location.
        for name, selector in list(self._follow_locations.items()):
            try:
                location = self._find_location(name)
            except ValueError:
                self._follow_locations.pop(name, None)
                continue
            matches = self._selected_from(world, selector, int(selector.get("player", 0)))
            if not matches:
                continue
            unit = matches[0]
            width = max(0, int(location.right) - int(location.left))
            height = max(0, int(location.bottom) - int(location.top))
            location.left = max(0, min(self.map_width - 1, int(unit.x) - width // 2))
            location.top = max(0, min(self.map_height - 1, int(unit.y) - height // 2))
            location.right = min(self.map_width - 1, location.left + width)
            location.bottom = min(self.map_height - 1, location.top + height)

        # Automatic spellcasting is a maintenance system, not a repeating trigger
        # action. The live adapter builds one atomic native command for the casts
        # selected this cycle, so Warcraft never sees a half-written spell order.
        auto_cycle = getattr(self, "_run_auto_spellcasting_cycle", None)
        if auto_cycle is not None and self.auto_spellcasting:
            return bool(auto_cycle(world))
        return True

    def _massive_prepare_events(self, current: dict[tuple[int, int], Any], previous: dict[tuple[int, int], Any]) -> None:
        now = time.monotonic()
        self._unit_damage_events = {}
        self._unit_heal_events = {}
        self._unit_attack_events = set()
        self._event_context = {}
        self._available_events = set()
        if getattr(self, "created_units", []): self._available_events.add("Unit Created")
        if getattr(self, "died_units", []): self._available_events.add("Unit Died")
        if getattr(self, "removed_units", []): self._available_events.add("Unit Removed")
        for key, unit in current.items():
            old = previous.get(key)
            if old is not None:
                delta = int(unit.health) - int(old.health)
                if delta < 0:
                    self._unit_damage_events[key] = -delta
                    self._available_events.add("Unit Damaged")
                elif delta > 0:
                    self._unit_heal_events[key] = delta
                    self._available_events.add("Unit Healed")
                if not (int(old.sflags) & 0x8000) and (int(unit.sflags) & 0x8000):
                    self._unit_attack_events.add(key)
                    self._available_events.add("Unit Under Attack")

        self._left_location_events = {}
        self._entered_location_events = {}
        scenario = getattr(self, "scenario", None)
        for location in getattr(scenario, "locations", []) if scenario else []:
            left: set[tuple[int, int]] = set()
            entered: set[tuple[int, int]] = set()
            for key, old in previous.items():
                if not self._inside(old, location):
                    continue
                new = current.get(key)
                if new is None or not self._inside(new, location):
                    left.add(key)
            for key, unit in current.items():
                if not self._inside(unit, location):
                    continue
                old = previous.get(key)
                if old is None or not self._inside(old, location):
                    entered.add(key)
            self._left_location_events[location.name] = left
            self._entered_location_events[location.name] = entered
            if left:
                self._available_events.add("Unit Left Location")
            if entered:
                self._available_events.add("Unit Entered Location")

            for key, unit in current.items():
                marker = (key, location.name)
                if self._inside(unit, location):
                    self._location_entered_at.setdefault(marker, now)
                else:
                    self._location_entered_at.pop(marker, None)
        active_keys = set(current)
        self._location_entered_at = {
            marker: entered for marker, entered in self._location_entered_at.items()
            if marker[0] in active_keys
        }

        switches = dict(getattr(self, "switches", {}))
        counters = {k: int(v) for k, v in dict(getattr(self, "counters", {})).items()}
        variables = dict(self.variables)
        self._switch_changes = {
            key: (self._last_seen_switches.get(key), value)
            for key, value in switches.items()
            if self._last_seen_switches.get(key) != value
        }
        self._counter_changes = {
            key: (int(self._last_seen_counters.get(key, 0)), int(value))
            for key, value in counters.items()
            if int(self._last_seen_counters.get(key, 0)) != int(value)
        }
        self._variable_changes = {
            key: (self._last_seen_variables.get(key), value)
            for key, value in variables.items()
            if self._last_seen_variables.get(key) != value
        }
        self._last_seen_switches = switches
        self._last_seen_counters = counters
        self._last_seen_variables = variables
        for timer in self.countdown_timers.values():
            timer.sync(now)

    # --------------------------------------------------------------- conditions
    def massive_value(self, kind: str, args: dict[str, Any], player: int) -> Any:
        if kind == "Random Chance":
            return self._massive_rng.randint(1, 100)
        if kind == "Countdown Timer":
            return int(math.ceil(self._timer(args.get("name", "Timer 1")).value()))
        if kind == "Timer Expired":
            timer = self._timer(args.get("name", "Timer 1"), create=False)
            return 1 if timer.ever_started and timer.value() <= 0 else 0
        if kind == "Variable":
            return self._numeric_variable(args.get("name", "Variable 1"))
        if kind == "Player Status":
            return self._owner_type_name(self._owner_type(int(args.get("player", player))))
        if kind == "Player Has No Buildings":
            owner = int(args.get("player", player))
            buildings = [u for u in self.units() if int(u.owner) == owner and 58 <= int(u.unit_type) <= 104]
            return 1 if not buildings else 0
        if kind == "Unit Health Percent":
            units = self._selected_units(args, player)
            if not units:
                return 0
            unit = units[0]
            return int(round(int(unit.health) * 100 / self._max_hp(unit)))
        if kind == "Unit Order":
            wanted = str(args.get("order", "Idle"))
            ids = ORDER_ACTIONS.get(wanted, set())
            return sum(
                1 for unit in self._selected_units(args, player)
                if int(unit.action) in ids or int(unit.next_action) in ids
            )
        if kind == "Unit Status":
            status = str(args.get("status", "Bloodlust"))
            def active(unit: Any) -> bool:
                if status == "Under Attack": return bool(int(unit.sflags) & 0x8000)
                if status == "Completed": return bool(int(unit.sflags) & 0x0080)
                if status == "Hidden": return bool(int(unit.sflags) & 0x0008)
                if status == "Selected": return bool(int(unit.sflags) & 0x2000)
                if status == "Invisibility": return int(unit.invis) != 0
                if status == "Unholy Armor": return int(unit.armor) != 0
                if status == "Bloodlust": return int(unit.rage) != 0
                if status == "Haste": return int(unit.warp) > 0
                if status == "Slow": return int(unit.warp) < 0
                if status == "Flame Shield": return int(unit.fire) != 0
                return False
            return sum(1 for unit in self._selected_units(args, player) if active(unit))
        if kind == "Unit Left Location":
            name = str(args.get("location", "Anywhere"))
            if name == "Anywhere":
                raise ValueError("Unit Left Location requires a named location")
            previous = getattr(self, "_previous_snapshot", {})
            keys = self._left_location_events.get(name, set())
            matches = [
                key for key in keys
                if key in previous and self._selector_matches(previous[key], args, player)
            ]
            if matches:
                self._set_event_context(kind, previous[matches[0]], 1, previous[matches[0]])
            return len(matches)
        if kind == "Unit Stayed In Location":
            name = str(args.get("location", "Anywhere"))
            if name == "Anywhere":
                raise ValueError("Unit Stayed In Location requires a named location")
            seconds = max(0.0, float(args.get("seconds", 1)))
            now = time.monotonic()
            current = getattr(self, "_snapshot", {})
            return sum(
                1 for marker, entered in self._location_entered_at.items()
                if marker[1] == name and now - entered >= seconds
                and marker[0] in current and self._selector_matches(current[marker[0]], args, player)
            )
        if kind == "Location Empty":
            name = str(args.get("location", "Anywhere"))
            units = self._selected_units({"player": int(args.get("player", -1)), "unit": args.get("unit", "Any"), "location": name}, player)
            return 1 if not units else 0
        if kind in {"Unit Damaged", "Unit Healed", "Unit Under Attack"}:
            current = getattr(self, "_snapshot", {})
            if kind == "Unit Damaged": keys = self._unit_damage_events
            elif kind == "Unit Healed": keys = self._unit_heal_events
            else: keys = self._unit_attack_events
            matches = [
                key for key in keys if key in current and self._selector_matches(current[key], args, player)
                and (str(args.get("location", "Anywhere")) == "Anywhere" or self._inside(current[key], self._find_location(str(args.get("location")))))
            ]
            if matches:
                first = matches[0]
                amount = int(keys.get(first, 1)) if isinstance(keys, dict) else 1
                self._set_event_context(kind, current[first], amount)
            return len(matches)
        if kind == "Switch Changed":
            return 1 if str(args.get("name", "Switch 1")) in self._switch_changes else 0
        if kind == "Counter Changed":
            name = str(args.get("name", "Counter 1"))
            before, after = self._counter_changes.get(name, (0, 0))
            return abs(int(after) - int(before))
        if kind == "Variable Changed":
            return 1 if str(args.get("name", "Variable 1")) in self._variable_changes else 0
        if kind == "Trigger Enabled":
            engine = getattr(self, "engine", None)
            if not engine:
                return "Disabled"
            trigger = engine.find_trigger(str(args.get("trigger", "")))
            return "Enabled" if trigger and trigger.enabled else "Disabled"
        if kind == "Location Exists":
            scenario = getattr(self, "scenario", None)
            return 1 if scenario and any(loc.name == str(args.get("location", "")) for loc in scenario.locations) else 0

        if kind == "Expression":
            return self._evaluate_expression(args.get("expression", "0"), player)
        if kind == "Unit Group Count":
            return len(self._group_units(args.get("group", "Unit Group 1")))
        if kind == "Unit Group Empty":
            return 1 if not self._group_units(args.get("group", "Unit Group 1")) else 0
        if kind == "Objective State":
            name = str(args.get("name", "Objective 1"))
            if name in self.completed_objectives:
                return "Completed"
            if name in self.objectives:
                return "Active"
            return "Missing"
        if kind == "Event Available":
            event_type = str(args.get("event_type", "Any"))
            if event_type == "Any":
                if not self._available_events:
                    return 0
                for candidate in sorted(self._available_events):
                    if self._prime_event_context(candidate):
                        break
                return 1
            available = event_type in self._available_events
            if available:
                self._prime_event_context(event_type)
            return 1 if available else 0
        if kind == "Auto Spellcasting":
            owner = int(args.get("player", player))
            state = "Enabled" if owner in self.auto_spellcasting else "Disabled"
            return state
        return MASSIVE_UNHANDLED

    # ------------------------------------------------------------------ actions
    def massive_action(self, kind: str, args: dict[str, Any], player: int) -> bool:

        if kind == "Enable Auto Spellcasting":
            owner = int(args.get("player", player))
            if not 0 <= owner <= 7:
                raise ValueError("Auto Spellcasting supports Player 1 through Player 8")
            profile = str(args.get("profile", "Balanced combat")).strip()
            if profile not in {"Balanced combat", "Offensive", "Support", "Full spellbook rotation"}:
                raise ValueError(f"Unknown Auto Spellcasting profile: {profile}")
            config = {
                "profile": profile,
                "range": max(3, min(32, int(args.get("range", 16)))),
                "cooldown": max(0.25, min(60.0, float(args.get("cooldown", 2.5)))),
                "max_casts": max(1, min(16, int(args.get("max_casts_per_cycle", 2)))),
                "mana_reserve": max(0, min(255, int(args.get("mana_reserve", 0)))),
                "keep_mana_full": bool(args.get("keep_mana_full", False)),
                "utility_spells": bool(args.get("utility_spells", False)),
                "group": str(args.get("group", "")).strip(),
                "log_casts": bool(args.get("log_casts", True)),
            }
            self.auto_spellcasting[owner] = config
            self.log(
                f"AUTO SPELLCASTING: enabled for P{owner + 1}; {profile}, "
                f"range {config['range']}, cooldown {config['cooldown']:.2f}s, "
                f"max {config['max_casts']} cast(s)/cycle"
                + ("; mana locked at 255" if config["keep_mana_full"] else "")
                + (f"; group {config['group']}" if config["group"] else "")
                + "; selective per-cast parking, automatic route resume, and atomic Heal/Flame Shield safety active"
            )
            return True
        if kind == "Disable Auto Spellcasting":
            owner_value = args.get("player", player)
            if str(owner_value).strip().casefold() in {"all", "all players"}:
                count = len(self.auto_spellcasting)
                self.auto_spellcasting.clear()
                self._auto_spell_parking.clear()
                self._auto_spell_parking_started.clear()
                self.log(f"AUTO SPELLCASTING: disabled for all players ({count} profile(s) removed); parked casters released")
            else:
                owner = int(owner_value)
                existed = self.auto_spellcasting.pop(owner, None) is not None
                active_owner_keys = {
                    self._unit_key_massive(unit) for unit in self.units()
                    if int(getattr(unit, "owner", -1)) == owner
                }
                self._auto_spell_parking.difference_update(active_owner_keys)
                for key in active_owner_keys:
                    self._auto_spell_parking_started.pop(key, None)
                self.log(f"AUTO SPELLCASTING: P{owner + 1} {'disabled' if existed else 'was already disabled'}; parked casters released")
            return True
        if kind == "Auto Cast Spells Now":
            handler = getattr(self, "_run_auto_spellcasting_cycle", None)
            if handler is None:
                raise RuntimeError("The live adapter does not expose automatic spellcasting")
            handler(self.units(), force=True, owner_filter=args.get("player", "All"))
            return True

        if kind == "Set Variable From Expression":
            name = str(args.get("name", "Variable 1")).strip()
            value = self._evaluate_expression(args.get("expression", "0"), player)
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            before = self.variables.get(name, 0)
            self._set_variable(name, value)
            self.log(f"VARIABLE EXPRESSION: {name} {before!r} -> {value!r}")
            return True
        if kind == "Set Counter From Expression":
            name = str(args.get("name", "Counter 1")).strip()
            value = max(-0x80000000, min(0x7FFFFFFF, int(self._evaluate_expression(args.get("expression", "0"), player))))
            before = int(self.counters.get(name, 0))
            self.counters[name] = value
            self.log(f"COUNTER EXPRESSION: {name} {before} -> {value}")
            return True
        if kind in {"Save Unit Group", "Add Units To Group"}:
            name = str(args.get("group", "Unit Group 1")).strip()
            units = self._selected_units(args, player)
            amount = args.get("amount", "All")
            if amount != "All": units = units[:max(0, int(amount))]
            keys = {self._unit_key_massive(unit) for unit in units}
            if kind == "Save Unit Group": self.unit_groups[name] = keys
            else: self.unit_groups.setdefault(name, set()).update(keys)
            self.log(f"UNIT GROUP: {name} now contains {len(self._group_units(name))} live unit(s)")
            return True
        if kind == "Clear Unit Group":
            name = str(args.get("group", "Unit Group 1")).strip()
            self.unit_groups.pop(name, None)
            self.log(f"UNIT GROUP: cleared {name}")
            return True
        if kind == "Order Unit Group":
            name = str(args.get("group", "Unit Group 1")).strip()
            units = self._group_units(name)
            destination = str(args.get("destination", "Anywhere"))
            if destination == "Anywhere":
                x, y = int(args.get("x", 0)), int(args.get("y", 0))
            else:
                loc = self._find_location(destination)
                x, y = (loc.left + loc.right) // 2, (loc.top + loc.bottom) // 2
            ordered = self._exact_group_order(units, str(args.get("order", "Attack")), x, y)
            self.log(f"UNIT GROUP ORDER: {name} -> {args.get('order', 'Attack')} ({x},{y}) for {ordered} unit(s)")
            return True
        if kind == "Set Unit Group Health Percent":
            name = str(args.get("group", "Unit Group 1")).strip()
            percent = max(1, min(100, int(args.get("percent", 100))))
            units = self._group_units(name)
            for unit in units:
                self.pm.write_ushort(unit.address + 0x22, max(1, round(self._max_hp(unit) * percent / 100)))
            self.log(f"UNIT GROUP HEALTH: {name} -> {percent}% on {len(units)} unit(s)")
            return True
        if kind == "Move Location To Event Unit":
            location = self._find_location(str(args.get("location", "Location 1")))
            unit = self._event_unit()
            if unit is None and not self._event_context:
                raise RuntimeError("No event-unit context is available for this trigger cycle")
            x = int(self._event_context.get("x", getattr(unit, "x", 0)))
            y = int(self._event_context.get("y", getattr(unit, "y", 0)))
            width, height = location.right - location.left, location.bottom - location.top
            location.left = max(0, min(self.map_width - 1 - width, x - width // 2))
            location.top = max(0, min(self.map_height - 1 - height, y - height // 2))
            location.right, location.bottom = location.left + width, location.top + height
            self.log(f"EVENT LOCATION: {location.name} centered at ({x},{y}) for {self._event_context.get('event_type', 'event')}")
            return True
        if kind == "Create Units At Event":
            if not self._event_context:
                raise RuntimeError("No event context is available for Create Units At Event")
            create_args = {
                "player": int(args.get("player", player)),
                "unit": int(args.get("unit", 0)),
                "amount": max(1, int(args.get("amount", 1))),
                "location": "Anywhere",
                "x": int(self._event_context.get("x", 0)) + int(args.get("x_offset", 0)),
                "y": int(self._event_context.get("y", 0)) + int(args.get("y_offset", 0)),
            }
            self.action("Create Units", create_args, player)
            return True
        if kind == "Set Variable From Event":
            name = str(args.get("name", "Event Value")).strip()
            field = str(args.get("field", "Damage"))
            mapping = {
                "Event Type": "event_type", "Player": "player", "Unit Type": "unit_type",
                "X": "x", "Y": "y", "Health": "health", "Mana": "mana", "Damage / amount": "amount",
            }
            key = mapping.get(field, "amount")
            value = self._event_context.get(key, "" if key == "event_type" else 0)
            if key == "player" and isinstance(value, int): value += 1
            self._set_variable(name, value)
            self.log(f"EVENT VARIABLE: {name}={value!r} from {field}")
            return True
        if kind == "Log Event Context":
            self.log("EVENT CONTEXT: " + (", ".join(f"{key}={value!r}" for key, value in sorted(self._event_context.items())) if self._event_context else "none"))
            return True
        if kind == "Create Wave":
            owner = int(args.get("player", player))
            unit_type = int(args.get("unit", 0))
            if not 0 <= owner <= 15: raise ValueError("Create Wave owner must be P1-P16")
            if not 0 <= unit_type < 58: raise ValueError("Create Wave currently supports mobile units only")
            amount = max(1, min(64, int(self._evaluate_expression(args.get("amount_expression", args.get("amount", 1)), player))))
            spawn_name = str(args.get("spawn_location", "Anywhere"))
            spawn_bounds = None
            if spawn_name == "Anywhere":
                spawn_x, spawn_y = int(args.get("spawn_x", 0)), int(args.get("spawn_y", 0))
            else:
                spawn_bounds = self._find_location(spawn_name)
                spawn_x, spawn_y = (spawn_bounds.left + spawn_bounds.right) // 2, (spawn_bounds.top + spawn_bounds.bottom) // 2
            points = self._formation_points(amount, spawn_x, spawn_y, str(args.get("formation", "Compact")), int(args.get("spacing", 1)), spawn_bounds)
            created: list[Any] = []
            for x, y in points:
                unit = self._create_unit(owner, unit_type, x, y)
                if unit is None: break
                facing = int(args.get("facing", -1))
                if facing >= 0: self.pm.write_uchar(unit.address + 0x0A, facing & 7)
                mana = max(0, min(255, int(args.get("mana", 0))))
                if mana: self.pm.write_uchar(unit.address + 0x26, mana)
                hp_percent = max(1, min(5000, int(args.get("health_percent", 100))))
                if hp_percent != 100: self.pm.write_ushort(unit.address + 0x22, max(1, min(65535, round(self._max_hp(unit) * hp_percent / 100))))
                created.append(unit)
            if len(created) != amount:
                raise RuntimeError(f"Create Wave placed {len(created)} of {amount} requested unit(s)")
            group = str(args.get("group", "Last Wave")).strip()
            if group: self.unit_groups[group] = {self._unit_key_massive(unit) for unit in created}
            order = str(args.get("order", "Attack"))
            ordered = 0
            if order != "None":
                destination = str(args.get("destination", "Anywhere"))
                if destination == "Anywhere":
                    dest_x, dest_y = int(args.get("destination_x", 0)), int(args.get("destination_y", 0))
                else:
                    loc = self._find_location(destination)
                    dest_x, dest_y = (loc.left + loc.right) // 2, (loc.top + loc.bottom) // 2
                ordered = self._exact_group_order(created, order, dest_x, dest_y)
            self.log(f"CREATE WAVE: P{owner + 1} type {unit_type}, {len(created)} unit(s), formation {args.get('formation', 'Compact')}, group {group or '(none)'}, ordered {ordered}")
            return True
        if kind == "Toggle Switch":
            name = str(args.get("name", "Switch 1"))
            self.switches[name] = "Cleared" if self.switches.get(name, "Cleared") == "Set" else "Set"
            self.log(f"SWITCH: {name} toggled to {self.switches[name]}")
            return True
        if kind == "Randomize Switch":
            name = str(args.get("name", "Switch 1"))
            self.switches[name] = self._massive_rng.choice(("Set", "Cleared"))
            self.log(f"SWITCH: {name} randomized to {self.switches[name]}")
            return True
        if kind in {"Copy Counter", "Multiply Counter", "Divide Counter", "Modulo Counter", "Clamp Counter", "Random Counter"}:
            name = str(args.get("name", "Counter 1")).strip()
            before = int(self.counters.get(name, 0))
            if kind == "Copy Counter":
                after = int(self.counters.get(str(args.get("source", "Counter 2")), 0))
            elif kind == "Multiply Counter":
                after = before * int(args.get("amount", 1))
            elif kind == "Divide Counter":
                divisor = int(args.get("amount", 1))
                if divisor == 0: raise ValueError("Divide Counter cannot divide by zero")
                after = int(before / divisor)
            elif kind == "Modulo Counter":
                divisor = int(args.get("amount", 1))
                if divisor == 0: raise ValueError("Modulo Counter cannot use zero")
                after = before % divisor
            elif kind == "Clamp Counter":
                low, high = int(args.get("minimum", 0)), int(args.get("maximum", 2147483647))
                if low > high: low, high = high, low
                after = max(low, min(high, before))
            else:
                low, high = int(args.get("minimum", 0)), int(args.get("maximum", 100))
                if low > high: low, high = high, low
                after = self._massive_rng.randint(low, high)
            after = max(-0x80000000, min(0x7FFFFFFF, int(after)))
            self.counters[name] = after
            self.log(f"COUNTER: {name} {before} -> {after} ({kind})")
            return True
        if kind in {"Set Variable", "Add Variable", "Subtract Variable", "Multiply Variable", "Divide Variable", "Modulo Variable", "Copy Variable", "Clamp Variable", "Random Variable"}:
            name = str(args.get("name", "Variable 1")).strip()
            before = self.variables.get(name, 0)
            if kind == "Set Variable":
                raw = args.get("value", 0)
                if str(args.get("value_type", "Number")) == "Text": after = str(raw)
                else: after = int(raw)
            elif kind == "Copy Variable":
                after = self.variables.get(str(args.get("source", "Variable 2")), 0)
            elif kind == "Random Variable":
                low, high = int(args.get("minimum", 0)), int(args.get("maximum", 100))
                if low > high: low, high = high, low
                after = self._massive_rng.randint(low, high)
            elif kind == "Clamp Variable":
                value = self._numeric_variable(name)
                low, high = int(args.get("minimum", 0)), int(args.get("maximum", 100))
                if low > high: low, high = high, low
                after = max(low, min(high, value))
            else:
                value = self._numeric_variable(name)
                amount = int(args.get("amount", 0))
                if kind == "Add Variable": after = value + amount
                elif kind == "Subtract Variable": after = value - amount
                elif kind == "Multiply Variable": after = value * amount
                elif kind == "Divide Variable":
                    if amount == 0: raise ValueError("Divide Variable cannot divide by zero")
                    after = int(value / amount)
                else:
                    if amount == 0: raise ValueError("Modulo Variable cannot use zero")
                    after = value % amount
            self._set_variable(name, after)
            self.log(f"VARIABLE: {name} {before!r} -> {after!r} ({kind})")
            return True
        if kind in {"Set Countdown Timer", "Start Countdown Timer", "Pause Countdown Timer", "Resume Countdown Timer", "Reset Countdown Timer"}:
            name = str(args.get("name", "Timer 1"))
            timer = self._timer(name)
            now = time.monotonic()
            if kind == "Set Countdown Timer":
                seconds = max(0.0, float(args.get("seconds", 0)))
                timer.duration = seconds; timer.remaining = seconds; timer.running = False; timer.ever_started = False
            elif kind == "Start Countdown Timer":
                seconds = max(0.0, float(args.get("seconds", timer.duration)))
                timer.duration = seconds; timer.remaining = seconds; timer.end_at = now + seconds; timer.running = True; timer.ever_started = True
            elif kind == "Pause Countdown Timer":
                timer.remaining = timer.value(now); timer.running = False
            elif kind == "Resume Countdown Timer":
                timer.end_at = now + timer.remaining; timer.running = timer.remaining > 0; timer.ever_started = True
            else:
                timer.remaining = timer.duration; timer.running = False; timer.ever_started = False
            self.log(f"TIMER: {name} {kind}; remaining {timer.value(now):.2f}s")
            return True
        if kind in {"Move Location", "Offset Location", "Resize Location", "Copy Location", "Randomize Location", "Follow Unit With Location", "Stop Following Location"}:
            name = str(args.get("location", "Location 1"))
            location = self._find_location(name)
            if kind == "Move Location":
                x, y = self._resolve_point(args)
                width, height = location.right - location.left, location.bottom - location.top
                location.left = max(0, min(self.map_width - 1, x - width // 2)); location.top = max(0, min(self.map_height - 1, y - height // 2))
                location.right = min(self.map_width - 1, location.left + width); location.bottom = min(self.map_height - 1, location.top + height)
            elif kind == "Offset Location":
                dx, dy = int(args.get("x_offset", 0)), int(args.get("y_offset", 0))
                width, height = location.right - location.left, location.bottom - location.top
                location.left = max(0, min(self.map_width - 1 - width, location.left + dx)); location.top = max(0, min(self.map_height - 1 - height, location.top + dy))
                location.right = location.left + width; location.bottom = location.top + height
            elif kind == "Resize Location":
                cx, cy = (location.left + location.right) // 2, (location.top + location.bottom) // 2
                width, height = max(1, int(args.get("width", 1))), max(1, int(args.get("height", 1)))
                location.left = max(0, cx - width // 2); location.top = max(0, cy - height // 2)
                location.right = min(self.map_width - 1, location.left + width - 1); location.bottom = min(self.map_height - 1, location.top + height - 1)
            elif kind == "Copy Location":
                source = self._find_location(str(args.get("source_location", "Location 1")))
                location.left, location.top, location.right, location.bottom = source.left, source.top, source.right, source.bottom
            elif kind == "Randomize Location":
                source = self._find_location(str(args.get("source_location", name)))
                width, height = location.right - location.left, location.bottom - location.top
                max_left = max(source.left, source.right - width)
                max_top = max(source.top, source.bottom - height)
                location.left = self._massive_rng.randint(source.left, max_left); location.top = self._massive_rng.randint(source.top, max_top)
                location.right = min(source.right, location.left + width); location.bottom = min(source.bottom, location.top + height)
            elif kind == "Follow Unit With Location":
                self._follow_locations[name] = {
                    "player": int(args.get("player", player)),
                    "unit": args.get("unit", "Any"),
                    "location": str(args.get("unit_location", "Anywhere")),
                }
            else:
                self._follow_locations.pop(name, None)
            self.log(f"LOCATION: {name} {kind}; bounds ({location.left},{location.top})-({location.right},{location.bottom})")
            return True
        if kind == "Replace Units":
            units = self._selected_units(args, player)
            amount = args.get("amount", "All")
            if amount != "All": units = units[:max(0, int(amount))]
            new_type = int(args.get("new_unit", 0))
            preserve_hp = bool(args.get("preserve_health_percent", True))
            replaced = 0
            for old in units:
                if int(old.unit_type) >= 58:
                    raise RuntimeError("Replace Units currently supports live mobile units only")
                created = self._create_unit(int(old.owner), new_type, int(old.x), int(old.y))
                if created is None:
                    raise RuntimeError(f"Could not place replacement at ({old.x},{old.y})")
                if preserve_hp:
                    ratio = int(old.health) / self._max_hp(old)
                    self.pm.write_ushort(created.address + 0x22, max(1, min(self._max_hp(created), round(self._max_hp(created) * ratio))))
                self.pm.write_uchar(created.address + 0x26, int(old.mana))
                self.pm.write_uchar(created.address + 0x0A, self.pm.read_uchar(old.address + 0x0A) & 7)
                self._remove_one_unit_safely(old)
                replaced += 1
            self.log(f"Replace Units: replaced {replaced} unit(s) with unit type {new_type}")
            return True
        if kind == "Set Unit Facing":
            facing = int(args.get("facing", 0)) & 7
            units = self._selected_units(args, player)
            for unit in units: self.pm.write_uchar(unit.address + 0x0A, facing)
            self.log(f"Set Unit Facing={facing} on {len(units)} unit(s)")
            return True
        if kind == "Set Unit Health Percent":
            percent = max(0, min(100, int(args.get("percent", 100))))
            units = self._selected_units(args, player)
            for unit in units: self.pm.write_ushort(unit.address + 0x22, round(self._max_hp(unit) * percent / 100))
            self.log(f"Set Unit Health Percent={percent}% on {len(units)} unit(s)")
            return True
        if kind == "Heal Units":
            amount = max(0, int(args.get("amount", 1)))
            units = self._selected_units(args, player)
            for unit in units:
                self.pm.write_ushort(unit.address + 0x22, min(self._max_hp(unit), int(unit.health) + amount))
            self.log(f"Heal Units: restored up to {amount} HP on {len(units)} unit(s)")
            return True
        if kind == "Apply Status Effect":
            status = str(args.get("status", "Bloodlust"))
            if status not in STATUS_OFFSETS: raise ValueError(f"Unknown status effect: {status}")
            ticks = int(args.get("ticks", 0))
            units = self._selected_units(args, player)
            for unit in units: self._write_status(unit, status, ticks)
            self.log(f"Apply Status Effect: {status} on {len(units)} unit(s)")
            return True
        if kind == "Clear Status Effects":
            status = str(args.get("status", "All"))
            units = self._selected_units(args, player)
            statuses = list(STATUS_OFFSETS) if status == "All" else [status]
            for unit in units:
                for item in statuses:
                    if item not in STATUS_OFFSETS: continue
                    offset, field_kind, _default = STATUS_OFFSETS[item]
                    if field_kind == "sword": self.pm.write_bytes(unit.address + offset, b"\0\0", 2)
                    else: self.pm.write_ushort(unit.address + offset, 0)
            self.log(f"Clear Status Effects: {status} on {len(units)} unit(s)")
            return True
        if kind in {"Make Invincible", "Make Vulnerable"}:
            units = self._selected_units(args, player)
            value = max(1, min(65535, int(args.get("ticks", 65535)))) if kind == "Make Invincible" else 0
            for unit in units:
                self.pm.write_ushort(unit.address + 0x46, value)
            self.log(f"{kind}: changed native Unholy Armor immunity timer on {len(units)} unit(s)")
            return True
        if kind == "Complete Buildings":
            units = self._selected_units(args, player)
            buildings = [unit for unit in units if 58 <= int(unit.unit_type) <= 104 and not (int(unit.sflags) & 0x0080)]
            completed = 0
            for unit in buildings:
                self._complete_building(unit); completed += 1
            self.log(f"Complete Buildings: Warcraft grow_structure completed {completed} building(s)")
            return True
        if kind == "Set Unit Color":
            color = max(0, min(7, int(args.get("color", 0))))
            units = self._selected_units(args, player)
            for unit in units: self.pm.write_uchar(unit.address + 0x2D, color)
            self.log(f"Set Unit Color={color} on {len(units)} unit(s)")
            return True
        if kind == "Center Camera":
            name = str(args.get("location", "Anywhere"))
            if name != "Anywhere":
                location = self._find_location(name)
                x, y = (location.left + location.right) // 2, (location.top + location.bottom) // 2
            else:
                x, y = int(args.get("x", 0)), int(args.get("y", 0))
            if not (0 <= x < self.map_width and 0 <= y < self.map_height):
                raise ValueError(f"Camera destination ({x},{y}) is outside the live map")
            self._call_cdecl(self.spell_path["vision_set_pos"], [x, y])
            self.log(f"Center Camera: local view centered at ({x},{y})")
            return True
        if kind in {"Set Score", "Set Kills", "Set Deaths"}:
            owner = int(args.get("player", player))
            amount = max(0, int(args.get("amount", 0)))
            if kind == "Set Score":
                name = "Score"; address = self.base + STAT_RVAS[name] + owner * 4; amount = min(0xFFFFFFFF, amount)
                self._dispatch_ops([("write_dword", address, amount)])
            else:
                category = str(args.get("category", "Men"))
                if category == "All":
                    raise ValueError(f"{kind} requires Men or Buildings so the two native tables remain explicit")
                name = f"{kind[4:]} {category}"; address = self.base + STAT_RVAS[name] + owner * 2; amount = min(0xFFFF, amount)
                self._dispatch_ops([("write_word", address, amount)])
            self.log(f"{kind}: P{owner + 1} {args.get('category', '')} -> {amount}")
            return True
        if kind in {"Set Objective", "Complete Objective", "Clear Objective"}:
            name = str(args.get("name", "Objective 1")).strip()
            if kind == "Set Objective":
                text = str(args.get("text", name)); self.objectives[name] = text; self.completed_objectives.discard(name)
                message = f"OBJECTIVE: {text}"
            elif kind == "Complete Objective":
                self.completed_objectives.add(name); message = f"OBJECTIVE COMPLETE: {self.objectives.get(name, name)}"
            else:
                self.objectives.pop(name, None); self.completed_objectives.discard(name); message = f"OBJECTIVE CLEARED: {name}"
            self.log(message)
            if bool(args.get("show_message", True)):
                self._game_message({"text": message, "recipients": args.get("recipients", "All active players"), "color": "Yellow / gold — native normal", "seconds": 4, "also_log": False}, player)
            return True
        if kind == "Display Leaderboard":
            metric = str(args.get("metric", "Score"))
            lines = [str(args.get("title", metric))]
            for owner in range(8):
                if metric == "Score": value = self._read_stat_table(owner, "Score")
                elif metric == "Kills": value = self._read_combat_stat(owner, "Kills", "All")
                elif metric == "Deaths": value = self._read_combat_stat(owner, "Deaths", "All")
                elif metric in {"Gold", "Lumber", "Oil"}: value = self._read_resource(owner, metric)
                else: value = int(self.counters.get(metric, 0))
                lines.append(f"P{owner + 1}: {value}")
            text = " | ".join(lines)
            self._game_message({"text": text, "recipients": args.get("recipients", "All active players"), "color": "Yellow / gold — native normal", "seconds": int(args.get("seconds", 8)), "also_log": True}, player)
            return True
        if kind == "Log State":
            names = sorted(set(self.variables) | set(self.counters) | set(self.countdown_timers))
            details = []
            for name in names:
                if name in self.variables: details.append(f"var {name}={self.variables[name]!r}")
                if name in self.counters: details.append(f"counter {name}={self.counters[name]}")
                if name in self.countdown_timers: details.append(f"timer {name}={self.countdown_timers[name].value():.2f}s")
            self.log("STATE: " + ("; ".join(details) if details else "no variables/counters/timers"))
            return True
        if kind == "Assert":
            source = str(args.get("source", "Variable"))
            name = str(args.get("name", "Variable 1"))
            expected = int(args.get("amount", 0)); op = str(args.get("comparison", "Exactly"))
            if source == "Variable": actual = self._numeric_variable(name)
            elif source == "Counter": actual = int(self.counters.get(name, 0))
            else: actual = int(math.ceil(self._timer(name).value()))
            passed = {"At least": actual >= expected, "At most": actual <= expected, "Exactly": actual == expected, "Not equal": actual != expected}.get(op, False)
            if not passed: raise RuntimeError(f"ASSERT FAILED: {source} {name} is {actual}, expected {op} {expected}")
            self.log(f"ASSERT PASSED: {source} {name}={actual} {op} {expected}")
            return True
        if kind == "Comment":
            return True
        return False
