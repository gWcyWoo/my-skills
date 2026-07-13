#!/usr/bin/env python3
"""Apply one packet-bounded model decision with stale-input protection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def set_path(document: object, dotted: str, value: object, *, create: bool = False) -> None:
    parts = dotted.split(".")
    current = document
    for index, part in enumerate(parts[:-1]):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, dict) and create:
            next_part = parts[index + 1]
            current[part] = [] if next_part.isdigit() or next_part == "-" else {}
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise ValueError(f"decision target does not exist: {dotted}")
    leaf = parts[-1]
    if isinstance(current, dict) and (leaf in current or create):
        current[leaf] = value
    elif isinstance(current, list) and leaf.isdigit() and int(leaf) < len(current):
        current[int(leaf)] = value
    elif isinstance(current, list) and leaf == "-" and create:
        current.append(value)
    else:
        raise ValueError(f"decision target does not exist: {dotted}")


def current_sources(packet: dict[str, Any]) -> dict[str, Path]:
    sources = packet.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise ValueError("packet sources must be a non-empty object")
    current: dict[str, Path] = {}
    for label, source in sources.items():
        if not isinstance(source, dict):
            raise ValueError(f"packet source is invalid: {label}")
        path = Path(str(source.get("path") or "")).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"packet source missing: {label}")
        if sha256(path) != source.get("sha256"):
            raise ValueError(f"packet source stale: {label}")
        current[label] = path
    return current


def plan_source(sources: dict[str, Path]) -> Path:
    matches = [
        path for path in sources.values() if path.name == "implementation_plan.json"
    ]
    if len(matches) != 1:
        raise ValueError("packet must bind exactly one implementation_plan.json")
    return matches[0]


def component_source(sources: dict[str, Path]) -> Path:
    matches = [
        path
        for path in sources.values()
        if path.name in {"shared_components.local.json", "batch_shared_components.json"}
    ]
    if len(matches) != 1:
        raise ValueError("packet must bind exactly one component registry")
    return matches[0]


def apply_component_decision(
    document: dict[str, Any], action: dict[str, Any], decision: dict[str, Any]
) -> None:
    signature = str((action.get("candidate") or {}).get("signature") or "")
    matches = [
        component
        for component in document.get("components") or []
        if str((component or {}).get("signature") or "") == signature
    ]
    if len(matches) != 1:
        raise ValueError(f"component candidate is not unique: {signature}")
    component = matches[0]
    component["status"] = "reuse" if decision["kind"] == "reuse" else "independent"
    component["model_decision"] = {
        "kind": decision["kind"],
        "value": decision.get("value"),
    }


def apply_declarative_updates(
    sources: dict[str, Path], action: dict[str, Any], decision: dict[str, Any]
) -> tuple[Path, dict[str, Any]]:
    allowed = set(action.get("allowedWritePaths") or [])
    required_by_decision = action.get("requiredWritePathsByDecision")
    updates = decision.get("updates")
    if (
        not allowed
        or not isinstance(required_by_decision, dict)
        or not isinstance(updates, list)
        or not updates
    ):
        raise ValueError("action has no bounded declarative updates")
    required = set(required_by_decision.get(str(decision.get("kind"))) or [])
    if not required:
        raise ValueError("decision has no declared write contract")
    documents: dict[Path, dict[str, Any]] = {}
    actual: set[str] = set()
    for update in updates:
        label = str((update or {}).get("source") or "")
        dotted = str((update or {}).get("path") or "")
        target = f"{label}:{dotted}"
        if target in actual:
            raise ValueError(f"decision update is duplicated: {target}")
        actual.add(target)
        if target not in allowed or label not in sources:
            raise ValueError(f"decision update is outside allowed paths: {target}")
        path = sources[label]
        document = documents.setdefault(path, load_object(path))
        set_path(document, dotted, update.get("value"), create=True)
    if actual != required:
        missing = sorted(required - actual)
        extra = sorted(actual - required)
        raise ValueError(
            f"decision writes differ from contract: missing={missing} extra={extra}"
        )
    if len(documents) != 1:
        raise ValueError("one decision may update exactly one source document")
    return next(iter(documents.items()))


def atomic_write(path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet", required=True)
    parser.add_argument("--decision", required=True)
    args = parser.parse_args()
    try:
        packet = load_object(Path(args.packet).expanduser().resolve())
        decision = load_object(Path(args.decision).expanduser().resolve())
        if packet.get("version") != 2:
            raise ValueError("packet version must be 2")
        action = packet.get("action") or {}
        allowed = action.get("allowedDecisions")
        if not isinstance(allowed, list) or decision.get("kind") not in allowed:
            raise ValueError(f"decision is not allowed: {decision.get('kind')}")
        sources = current_sources(packet)
        action_kind = action.get("kind")
        if action_kind == "fill_plan_judgment":
            path = plan_source(sources)
            document = load_object(path)
            target = str(action.get("target") or (action.get("modelField") or {}).get("path") or "")
            set_path(document, target, decision.get("value"))
        elif action_kind == "resolve_component_semantics":
            path = component_source(sources)
            document = load_object(path)
            apply_component_decision(document, action, decision)
        else:
            path, document = apply_declarative_updates(sources, action, decision)
        atomic_write(path, document)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(f"ERROR: model decision rejected: {error}") from error
    print(f"ok model decision: {decision['kind']} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
