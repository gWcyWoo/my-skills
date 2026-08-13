"""Pure derivation of required data verification case identifiers."""
from __future__ import annotations


def required_data_cases(bindings: dict, runtime_manifest: dict | None = None) -> list[str]:
    cases = []
    for entry in bindings.get("bindings") or []:
        if not (entry.get("binding") or {}).get("field"):
            continue
        state = entry.get("state")
        qualifier = f"{state}:" if state is not None else ""
        cases.append(f"DATA-SLOT:{qualifier}{entry.get('node')}")
    for operation in (runtime_manifest or {}).get("operations") or []:
        operation_id = str(operation.get("id"))
        cases.append(f"DATA-REPO:{operation_id}")
        cases.extend(
            f"DATA-STATE:{operation_id}:{state}"
            for state in operation.get("requiredStates") or []
        )
    return cases
