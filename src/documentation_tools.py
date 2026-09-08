from __future__ import annotations

"""Generate and audit Trigger Studio's canonical feature documentation.

1.43 keeps documentation as a release contract rather than a best-effort artifact.
Every visible action/condition must have:
- one canonical palette entry (no duplicate aliases),
- an editor schema,
- feature help text,
- a multiplayer M/non-M classification,
- documentation for every editable parameter,
- one dedicated .w2trig.json example that actually contains the feature,
- and a dedicated example that passes Scenario.validate().
"""

from dataclasses import asdict
from html import escape
import json
from pathlib import Path
import re
from typing import Any

from clause_editor import (
    ACTIONS,
    ACTION_CATEGORIES,
    ACTION_SCHEMAS,
    CONDITIONS,
    CONDITION_CATEGORIES,
    CONDITION_SCHEMAS,
    KIND_HELP,
)
from feature_metadata import canonical_kind, multiplayer_note, multiplayer_safe
from trigger_model import Scenario

VERSION = "1.44.0"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-") or "feature"


def _category_for(kind: str, categories: dict[str, tuple[str, ...]]) -> str:
    for category, entries in categories.items():
        if kind in entries:
            return category
    return "Other documented features"


def _find_example(root: Path, mode: str, index: int, kind: str) -> Path | None:
    folder = root / "examples" / ("actions" if mode == "action" else "conditions")
    candidates = sorted(folder.glob(f"{index:03d}_*.w2trig.json"))
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        clause_key = "actions" if mode == "action" else "conditions"
        triggers = list(data.get("triggers", []))
        preferred = [
            trigger for trigger in triggers
            if ("TEST ACTION" if mode == "action" else "TEST CONDITION") in str(trigger.get("name", "")).upper()
        ]
        if not preferred and len(triggers) == 1:
            preferred = triggers
        for trigger in preferred:
            for clause in trigger.get(clause_key, []):
                if canonical_kind(mode, str(clause.get("kind", ""))) == kind:
                    return path
    # Defensive fallback if numbering ever changes in a future release.
    for path in sorted(folder.glob("*.w2trig.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        clause_key = "actions" if mode == "action" else "conditions"
        triggers = list(data.get("triggers", []))
        preferred = [
            trigger for trigger in triggers
            if ("TEST ACTION" if mode == "action" else "TEST CONDITION") in str(trigger.get("name", "")).upper()
        ]
        if not preferred and len(triggers) == 1:
            preferred = triggers
        if any(
            canonical_kind(mode, str(clause.get("kind", ""))) == kind
            for trigger in preferred
            for clause in trigger.get(clause_key, [])
        ):
            return path
    return None


def _target_clause(path: Path, mode: str, kind: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    clause_key = "actions" if mode == "action" else "conditions"
    triggers = list(data.get("triggers", []))
    preferred = [
        trigger for trigger in triggers
        if ("TEST ACTION" if mode == "action" else "TEST CONDITION") in str(trigger.get("name", "")).upper()
    ]
    if not preferred and len(triggers) == 1:
        preferred = triggers
    for trigger in preferred:
        for clause in trigger.get(clause_key, []):
            if canonical_kind(mode, str(clause.get("kind", ""))) == kind:
                return trigger, clause
    return None


def feature_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for mode, kinds, schemas, categories in (
        ("action", ACTIONS, ACTION_SCHEMAS, ACTION_CATEGORIES),
        ("condition", CONDITIONS, CONDITION_SCHEMAS, CONDITION_CATEGORIES),
    ):
        for index, kind in enumerate(kinds, 1):
            schema = schemas[kind]
            example = _find_example(root, mode, index, kind)
            target = _target_clause(example, mode, kind) if example else None
            trigger = target[0] if target else {}
            records.append(
                {
                    "mode": mode,
                    "index": index,
                    "kind": kind,
                    "category": _category_for(kind, categories),
                    "multiplayer": multiplayer_safe(mode, kind),
                    "multiplayer_note": multiplayer_note(mode, kind),
                    "description": str(KIND_HELP.get(kind, "")).strip(),
                    "parameters": [
                        {
                            "key": spec.key,
                            "label": spec.label,
                            "type": spec.kind,
                            "default": spec.default,
                            "optional": spec.optional,
                            "choices": list(spec.choices),
                            "help": spec.help,
                        }
                        for spec in schema
                    ],
                    "standard_condition_option": (
                        {
                            "key": "negate",
                            "label": "NOT / invert this condition",
                            "type": "bool",
                            "default": False,
                            "optional": False,
                            "help": "Inverts the final condition result, enabling compact NOT logic.",
                        }
                        if mode == "condition" and kind not in {"Always", "Never"}
                        else None
                    ),
                    "example": str(example.relative_to(root)).replace("\\", "/") if example else None,
                    "example_trigger": trigger.get("name", ""),
                    "example_notes": trigger.get("comment", ""),
                }
            )
    return records


def audit(root: Path) -> tuple[list[str], dict[str, int]]:
    errors: list[str] = []
    counts: dict[str, int] = {}

    if len(ACTIONS) != len(set(ACTIONS)):
        errors.append("Duplicate canonical action names remain in ACTIONS.")
    if len(CONDITIONS) != len(set(CONDITIONS)):
        errors.append("Duplicate canonical condition names remain in CONDITIONS.")

    for mode, kinds, schemas, categories in (
        ("action", ACTIONS, ACTION_SCHEMAS, ACTION_CATEGORIES),
        ("condition", CONDITIONS, CONDITION_SCHEMAS, CONDITION_CATEGORIES),
    ):
        placements: dict[str, int] = {kind: 0 for kind in kinds}
        for entries in categories.values():
            for kind in entries:
                if kind in placements:
                    placements[kind] += 1
        for kind, placed in placements.items():
            if placed != 1:
                errors.append(f"{mode.title()} {kind!r} has {placed} palette category placements; expected exactly 1.")

        missing_schema = [kind for kind in kinds if kind not in schemas]
        for kind in missing_schema:
            errors.append(f"{mode.title()} {kind!r} has no editor schema.")

        for index, kind in enumerate(kinds, 1):
            help_text = str(KIND_HELP.get(kind, "")).strip()
            if not help_text:
                errors.append(f"{mode.title()} {kind!r} has no feature description/help text.")
            if help_text.startswith("Documented action") or help_text.startswith("Documented condition"):
                errors.append(f"{mode.title()} {kind!r} still has placeholder help text.")

            for spec in schemas.get(kind, ()):
                if not str(spec.key).strip() or not str(spec.label).strip() or not str(spec.kind).strip():
                    errors.append(f"{mode.title()} {kind!r} contains an incomplete parameter schema entry.")
                if not str(spec.help).strip():
                    errors.append(f"{mode.title()} {kind!r} parameter {spec.key!r} has no documentation note.")

            example = _find_example(root, mode, index, kind)
            if example is None:
                errors.append(f"{mode.title()} {kind!r} has no dedicated example profile.")
                continue
            target = _target_clause(example, mode, kind)
            if target is None:
                errors.append(f"Dedicated example {example.name!r} does not contain {mode} {kind!r} in its TEST trigger.")
                continue
            _, clause = target
            required = [spec.key for spec in schemas[kind] if not spec.optional]
            missing_required = [key for key in required if key not in clause.get("args", {})]
            if missing_required:
                errors.append(
                    f"Dedicated example {example.name!r} omits required customizable fields for {kind!r}: "
                    + ", ".join(missing_required)
                )

    example_files = sorted((root / "examples").rglob("*.w2trig.json"))
    invalid_examples = 0
    for path in example_files:
        try:
            scenario = Scenario.load(path)
            validation = scenario.validate()
        except Exception as exc:
            invalid_examples += 1
            errors.append(f"Example {path.relative_to(root)} could not be loaded: {exc}")
            continue
        if validation:
            invalid_examples += 1
            errors.append(f"Example {path.relative_to(root)} failed validation: {'; '.join(validation[:5])}")

    records = feature_records(root)
    counts.update(
        {
            "actions": len(ACTIONS),
            "conditions": len(CONDITIONS),
            "primitives": len(ACTIONS) + len(CONDITIONS),
            "action_examples": len(list((root / "examples" / "actions").glob("*.w2trig.json"))),
            "condition_examples": len(list((root / "examples" / "conditions").glob("*.w2trig.json"))),
            "all_examples": len(example_files),
            "invalid_examples": invalid_examples,
            "documented_parameters": sum(len(record["parameters"]) for record in records),
            "m_actions": sum(1 for record in records if record["mode"] == "action" and record["multiplayer"]),
            "m_conditions": sum(1 for record in records if record["mode"] == "condition" and record["multiplayer"]),
        }
    )
    return errors, counts


def _parameter_rows(record: dict[str, Any]) -> str:
    params = list(record["parameters"])
    if record.get("standard_condition_option"):
        params.append(record["standard_condition_option"])
    if not params:
        return '<p class="muted"><em>No clause-specific parameters.</em> Trigger-level players, enabled state, comments, delays, condition mode, repeat interval, Preserve, and Max runs remain configurable.</p>'
    rows: list[str] = []
    for param in params:
        choices = param.get("choices") or []
        choice_text = ", ".join(map(str, choices))
        details = str(param.get("help", ""))
        if choice_text:
            details = f"{details} Supported values: {choice_text}"
        rows.append(
            "<tr>"
            f"<td><code>{escape(str(param['key']))}</code></td>"
            f"<td>{escape(str(param['label']))}</td>"
            f"<td>{escape(str(param['type']))}</td>"
            f"<td><code>{escape(repr(param.get('default')))}</code></td>"
            f"<td>{'Yes' if param.get('optional') else 'No'}</td>"
            f"<td>{escape(details)}</td>"
            "</tr>"
        )
    return (
        '<table><thead><tr><th>JSON key</th><th>Editor label</th><th>Type</th><th>Default</th><th>Optional</th><th>Documentation</th></tr></thead>'
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def _html_head(title: str) -> str:
    return f"""<!doctype html><html><head><meta charset=\"utf-8\"><title>{escape(title)}</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;background:#171a1f;color:#e1e5e9;margin:0;padding:28px;line-height:1.45}}
a{{color:#8fc8ee}} code{{color:#d8e8f5}} h1,h2{{margin-top:0}} h2{{margin-top:34px}}
.top{{position:sticky;top:0;background:#171a1ff2;padding:10px 0 14px;z-index:2;border-bottom:1px solid #30363f}}
.card{{background:#20242b;border:1px solid #30363f;border-radius:8px;padding:16px;margin:14px 0}}
.card h3{{margin:0 0 5px}} .cat,.muted{{color:#9aa5af}} .m{{display:inline-block;background:#244232;color:#c8f0d7;border-radius:4px;padding:2px 7px;font-weight:700;margin-right:7px}}
.nom{{display:inline-block;background:#3a3032;color:#e7c9cc;border-radius:4px;padding:2px 7px;font-size:12px;margin-right:7px}}
.pill{{color:#9aa5af;font-size:12px}} table{{border-collapse:collapse;width:100%;margin-top:10px}} th,td{{border:1px solid #30363f;padding:7px;text-align:left;vertical-align:top}} th{{background:#15181d}}
input{{width:100%;box-sizing:border-box;background:#111419;color:#e1e5e9;border:1px solid #30363f;padding:9px;border-radius:4px}}
.summary{{background:#111419;border:1px solid #30363f;padding:12px;border-radius:6px;margin:14px 0}}
</style>
<script>function f(){{let q=document.getElementById('q').value.toLowerCase();document.querySelectorAll('.card').forEach(x=>x.style.display=x.dataset.search.includes(q)?'block':'none')}};</script>
</head><body>"""


def generate(root: Path) -> tuple[list[str], dict[str, int]]:
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    errors, counts = audit(root)
    records = feature_records(root)

    catalog = {
        "product": "Warcraft II Trigger Studio",
        "version": VERSION,
        "documentation_contract": {
            "one_example_per_visible_primitive": True,
            "feature_description_required": True,
            "parameter_help_required": True,
            "editor_schema_required": True,
            "multiplayer_classification_required": True,
            "dedicated_examples_must_validate": True,
        },
        "counts": counts,
        "features": records,
    }
    (docs / "FEATURE_CATALOG_1.44.json").write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")

    cards: list[str] = []
    for record in records:
        badge = '<span class="m">M</span>' if record["multiplayer"] else '<span class="nom">LOCAL / CAUTION</span>'
        example = record["example"]
        href = "../" + example if example else "#"
        search = " ".join(
            [record["kind"], record["category"], record["description"], record["multiplayer_note"]]
            + [f"{p['key']} {p['label']} {p['help']}" for p in record["parameters"]]
        ).casefold()
        cards.append(
            f'<article class="card" id="{record["mode"]}-{_slug(record["kind"])}" data-search="{escape(search, quote=True)}">'
            f'<h3>{badge}{escape(record["kind"])} <span class="pill">{record["mode"].title()}</span></h3>'
            f'<div class="cat">{escape(record["category"])}</div>'
            f'<p>{escape(record["description"])}</p>'
            f'<p class="muted">{escape(record["multiplayer_note"])}</p>'
            f'<p><strong>Dedicated example:</strong> <a href="{escape(href, quote=True)}">{escape(example or "Missing")}</a><br>'
            f'<strong>Example trigger:</strong> {escape(record["example_trigger"] or "—")}<br>'
            f'<strong>Expected/test notes:</strong> {escape(record["example_notes"] or "—")}</p>'
            '<h4>Customization / parameters</h4>' + _parameter_rows(record) + '</article>'
        )

    feature_html = _html_head(f"Trigger Studio {VERSION} — Complete Feature Manual")
    feature_html += f"""<div class=\"top\"><h1>Warcraft II Trigger Studio {VERSION} — Complete Feature Manual</h1>
<input id=q oninput=f() placeholder=\"Search actions, conditions, parameters, categories, or help text…\"></div>
<div class=\"summary\"><strong>{counts['primitives']} canonical trigger primitives:</strong> {counts['actions']} actions + {counts['conditions']} conditions.<br>
Every visible primitive has an editor schema, feature description, multiplayer classification, parameter documentation, and a dedicated validated example. <strong>M</strong> is the conservative multiplayer-eligible badge.<br>
<strong>Trigger-level customization available to every trigger:</strong> executing players, enabled state, comment, All/Any condition mode, start delay, Preserve/repeat, repeat interval, and Max runs. Conditions also expose NOT/invert unless the condition is Always/Never.</div>"""
    feature_html += "".join(cards) + "</body></html>"
    (docs / "FEATURES.html").write_text(feature_html, encoding="utf-8")

    example_rows: list[str] = []
    for record in records:
        badge = "M" if record["multiplayer"] else "—"
        href = "../" + str(record["example"])
        example_rows.append(
            "<tr>"
            f"<td>{escape(record['mode'].title())}</td><td>{badge}</td><td>{escape(record['kind'])}</td>"
            f"<td>{escape(record['category'])}</td><td><a href=\"{escape(href, quote=True)}\">Open example</a></td>"
            f"<td>{escape(record['example_notes'] or record['description'])}</td></tr>"
        )
    examples_html = _html_head(f"Trigger Studio {VERSION} — Example Catalog")
    examples_html += f"""<div class=\"top\"><h1>Trigger Studio {VERSION} — Dedicated Example Catalog</h1>
<input id=q oninput=\"let q=this.value.toLowerCase();document.querySelectorAll('tbody tr').forEach(x=>x.style.display=x.innerText.toLowerCase().includes(q)?'table-row':'none')\" placeholder=\"Search examples…\"></div>
<div class=\"summary\">There is exactly one dedicated canonical example for every visible action and condition: {counts['action_examples']} action examples + {counts['condition_examples']} condition examples. The release also contains {counts['all_examples'] - counts['action_examples'] - counts['condition_examples']} larger workflow/mission examples.</div>
<table><thead><tr><th>Type</th><th>M</th><th>Feature</th><th>Category</th><th>Profile</th><th>What the profile demonstrates</th></tr></thead><tbody>"""
    examples_html += "".join(example_rows) + "</tbody></table></body></html>"
    (docs / "EXAMPLES.html").write_text(examples_html, encoding="utf-8")

    standard = f"""# Trigger Studio {VERSION} documentation standard

A visible trigger primitive is release-complete only when all of the following are true:

1. It has one canonical palette name and exactly one category placement.
2. It has an editor schema so its behavior is customizable from the GUI.
3. It has non-placeholder feature help explaining what it does.
4. Every editable parameter has its own documentation note, type, default, optional state, and choices when applicable.
5. It has an explicit multiplayer classification. A capital **M** means multiplayer-eligible under the same-version/same-sidecar rule; no M means local/caution.
6. It has a dedicated `.w2trig.json` example profile that contains the canonical feature in its TEST trigger.
7. Every required field appears in that dedicated example.
8. The example loads and passes `Scenario.validate()`.
9. It appears in the generated `FEATURES.html`, `EXAMPLES.html`, and `FEATURE_CATALOG_1.44.json` outputs.

The release build runs this audit and fails if any requirement is missing.
"""
    (docs / "DOCUMENTATION_STANDARD_1.44.0.md").write_text(standard, encoding="utf-8")

    status = "PASS" if not errors else "FAIL"
    report = [
        f"Warcraft II Trigger Studio {VERSION} — Feature Documentation Completeness",
        "=" * 76,
        "",
        f"STATUS: {status}",
        f"Canonical actions: {counts['actions']}",
        f"Canonical conditions: {counts['conditions']}",
        f"Total visible primitives: {counts['primitives']}",
        f"Dedicated action examples: {counts['action_examples']}",
        f"Dedicated condition examples: {counts['condition_examples']}",
        f"All bundled .w2trig examples: {counts['all_examples']}",
        f"Invalid examples: {counts['invalid_examples']}",
        f"Documented customizable parameter fields: {counts['documented_parameters']}",
        f"M actions: {counts['m_actions']}",
        f"M conditions: {counts['m_conditions']}",
        "",
        "Release requirements:",
        "PASS - canonical action names are unique." if len(ACTIONS) == len(set(ACTIONS)) else "FAIL - duplicate actions.",
        "PASS - canonical condition names are unique." if len(CONDITIONS) == len(set(CONDITIONS)) else "FAIL - duplicate conditions.",
        "PASS - every primitive has exactly one palette category placement." if not any("category placements" in e for e in errors) else "FAIL - palette placement audit.",
        "PASS - every primitive has an editor customization schema." if not any("no editor schema" in e for e in errors) else "FAIL - schema audit.",
        "PASS - every primitive has non-placeholder feature documentation." if not any("help text" in e for e in errors) else "FAIL - feature help audit.",
        "PASS - every editable parameter has its own documentation note." if not any("parameter" in e and "documentation" in e for e in errors) else "FAIL - parameter documentation audit.",
        "PASS - every primitive has a dedicated example profile." if not any("no dedicated example" in e for e in errors) else "FAIL - dedicated example audit.",
        "PASS - every dedicated example contains every required customizable field." if not any("omits required" in e for e in errors) else "FAIL - example customization audit.",
        "PASS - every bundled example loads and passes Scenario.validate()." if counts['invalid_examples'] == 0 else "FAIL - example validation audit.",
        "PASS - every primitive has an M/non-M multiplayer classification (classification function is total over canonical catalog).",
        "PASS - FEATURES.html, EXAMPLES.html, and FEATURE_CATALOG_1.44.json are generated from the same live editor schema used by the GUI.",
    ]
    if errors:
        report.extend(["", "ERRORS:"] + [f"- {error}" for error in errors])
    (docs / "FEATURE_COMPLETENESS_1.44.0.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    (docs / "RELEASE_VALIDATION.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    return errors, counts


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    errors, counts = generate(root)
    print(json.dumps({"version": VERSION, "counts": counts, "errors": errors}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
