#!/usr/bin/env python3
"""Validated provenance for design text whose runtime value is supplied by an API."""

from __future__ import annotations

import json
from pathlib import Path


class DynamicContentContractError(ValueError):
    pass


def load_api_dynamic_nodes(path: str | Path | None) -> set[str]:
    if path is None:
        return set()
    contract_path = Path(path)
    try:
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DynamicContentContractError(f"cannot read data-slot bindings: {exc}") from exc
    bindings = payload.get("bindings") if isinstance(payload, dict) else None
    if not isinstance(bindings, list):
        raise DynamicContentContractError("data-slot bindings must contain a bindings array")

    nodes: set[str] = set()
    for index, entry in enumerate(bindings):
        if not isinstance(entry, dict) or entry.get("confirmedByModel") is not True:
            continue
        source = entry.get("contentSource")
        if not isinstance(source, dict) or source.get("kind") != "api":
            continue
        node = str(entry.get("node") or "").strip()
        binding = entry.get("binding")
        field = str(binding.get("field") or "").strip() if isinstance(binding, dict) else ""
        evidence = str(source.get("evidence") or "").strip()
        missing = [name for name, value in (("node", node), ("binding.field", field), ("contentSource.evidence", evidence)) if not value]
        if missing:
            raise DynamicContentContractError(
                f"bindings[{index}] confirmed API source lacks {', '.join(missing)}"
            )
        nodes.add(node)
    return nodes
