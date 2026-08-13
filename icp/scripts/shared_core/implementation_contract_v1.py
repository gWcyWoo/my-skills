"""Platform-neutral source projection and implementation-contract validation."""

from __future__ import annotations

import hashlib
import json


SHA256_HEX_LENGTH = 64
EVIDENCE_KINDS = {"contract", "design", "unit", "integration", "e2e", "visual", "runtime"}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _lines(value: str) -> list[tuple[int, str]]:
    return [
        (index, line)
        for index, line in enumerate(value.splitlines(), start=1)
        if line.strip()
    ]


def _source_clause(
    *,
    page_id: str,
    source_path: str,
    source_kind: str,
    exact_text: str,
    required_evidence: list[str],
) -> dict[str, object]:
    identity = {
        "page_id": page_id,
        "source_path": source_path,
        "exact_text": exact_text,
    }
    return {
        "clause_id": f"source:{hashlib.sha256(canonical_bytes(identity)).hexdigest()}",
        "page_id": page_id,
        "source_path": source_path,
        "source_kind": source_kind,
        "exact_text": exact_text,
        "source_digest": hashlib.sha256(exact_text.encode("utf-8")).hexdigest(),
        "required_evidence": required_evidence,
    }


def build_source_clauses(members: list[object]) -> list[dict[str, object]]:
    """Project every non-empty mapped source line without product semantics."""
    result: list[dict[str, object]] = []
    for member in members:
        if not isinstance(member, dict):
            raise ValueError("flow member is invalid")
        page_id = str(member["page_id"])
        contract = member.get("source_contract")
        if not isinstance(contract, dict):
            raise ValueError("source contract is required")
        for field, source_kind, evidence in (
            ("title", "interface", ["contract"]),
            ("route", "interface", ["contract"]),
            ("design_ref", "design", ["design"]),
        ):
            value = contract.get(field)
            if not isinstance(value, str):
                raise ValueError(f"source contract {field} is invalid")
            for line_number, line in _lines(value):
                result.append(
                    _source_clause(
                        page_id=page_id,
                        source_path=f"/members/{page_id}/source_contract/{field}/lines/{line_number}",
                        source_kind=source_kind,
                        exact_text=line,
                        required_evidence=evidence,
                    )
                )
        interaction = contract.get("interaction")
        if not isinstance(interaction, str):
            raise ValueError("source contract interaction is invalid")
        for line_number, line in _lines(interaction):
            result.append(
                _source_clause(
                    page_id=page_id,
                    source_path=f"/members/{page_id}/source_contract/interaction/lines/{line_number}",
                    source_kind="behavior",
                    exact_text=line,
                    required_evidence=["integration"],
                )
            )
        requirement_sections = contract.get("requirement_sections")
        if not isinstance(requirement_sections, list):
            raise ValueError("source contract requirement sections are invalid")
        for section_index, section in enumerate(requirement_sections):
            if not isinstance(section, dict) or not isinstance(section.get("value"), str):
                raise ValueError("source contract requirement section is invalid")
            for line_number, line in _lines(section["value"]):
                result.append(
                    _source_clause(
                        page_id=page_id,
                        source_path=(
                            f"/members/{page_id}/source_contract/requirement_sections/"
                            f"{section_index}/value/lines/{line_number}"
                        ),
                        source_kind="requirement",
                        exact_text=line,
                        required_evidence=["integration"],
                    )
                )
        acceptance_sections = contract.get("acceptance_sections")
        if not isinstance(acceptance_sections, list):
            raise ValueError("source contract acceptance sections are invalid")
        evidence_by_prefix = {"UT": "unit", "IT": "integration", "E2E": "e2e"}
        for section_index, section in enumerate(acceptance_sections):
            if (
                not isinstance(section, dict)
                or not isinstance(section.get("prefix"), str)
                or not isinstance(section.get("value"), str)
            ):
                raise ValueError("source contract acceptance section is invalid")
            evidence = evidence_by_prefix.get(section["prefix"], "contract")
            for line_number, line in _lines(section["value"]):
                result.append(
                    _source_clause(
                        page_id=page_id,
                        source_path=(
                            f"/members/{page_id}/source_contract/acceptance_sections/"
                            f"{section_index}/value/lines/{line_number}"
                        ),
                        source_kind="acceptance",
                        exact_text=line,
                        required_evidence=[evidence],
                    )
                )
    return result


def validate_context_source_clauses(
    clauses: object,
    *,
    implemented_page_ids: set[str],
) -> list[dict[str, object]]:
    """Validate optional task-local behavior sources without universal semantics."""
    if not isinstance(clauses, list):
        raise ValueError("implementation contract context sources are invalid")
    clause_ids: set[str] = set()
    expected_keys = {
        "clause_id",
        "page_id",
        "source_path",
        "source_kind",
        "exact_text",
        "source_digest",
        "required_evidence",
        "origin",
        "provenance_path",
        "provenance_sha256",
    }
    for clause in clauses:
        if not isinstance(clause, dict) or set(clause) != expected_keys:
            raise ValueError("implementation contract context sources are invalid")
        clause_id = clause["clause_id"]
        exact_text = clause["exact_text"]
        required_evidence = clause["required_evidence"]
        if (
            not isinstance(clause_id, str)
            or not clause_id
            or clause_id in clause_ids
            or clause["page_id"] not in implemented_page_ids
            or not isinstance(clause["source_path"], str)
            or not clause["source_path"].strip()
            or clause["source_kind"] != "behavior"
            or not isinstance(exact_text, str)
            or not exact_text.strip()
            or clause["source_digest"]
            != hashlib.sha256(exact_text.encode("utf-8")).hexdigest()
            or not isinstance(required_evidence, list)
            or "integration" not in required_evidence
            or len(required_evidence) != len(set(required_evidence))
            or any(
                value not in {"unit", "integration", "e2e", "runtime"}
                for value in required_evidence
            )
            or clause["origin"] not in {"project-contract", "user-decision"}
            or not isinstance(clause["provenance_path"], str)
            or not clause["provenance_path"]
            or not isinstance(clause["provenance_sha256"], str)
            or len(clause["provenance_sha256"]) != SHA256_HEX_LENGTH
        ):
            raise ValueError("implementation contract context sources are invalid")
        clause_ids.add(clause_id)
    return clauses


def validate_design_contracts(
    design_contracts: object,
    *,
    implemented_page_ids: set[str],
) -> list[dict[str, object]]:
    if not isinstance(design_contracts, list):
        raise ValueError("implementation contract design contracts are invalid")
    page_ids: list[str] = []
    state_ids: set[str] = set()
    reference_ids: set[str] = set()
    for design in design_contracts:
        if not isinstance(design, dict) or set(design) != {
            "design_id",
            "page_id",
            "reference_artifacts",
            "states",
        }:
            raise ValueError("implementation contract design contracts are invalid")
        page_id = design["page_id"]
        references = design["reference_artifacts"]
        states = design["states"]
        if (
            not isinstance(page_id, str)
            or not page_id
            or not isinstance(references, list)
            or not references
            or not isinstance(states, list)
            or not states
        ):
            raise ValueError("every implemented page requires a design state contract")
        page_ids.append(page_id)
        local_reference_ids: set[str] = set()
        local_reference_sha256: dict[str, str] = {}
        for artifact in references:
            if (
                not isinstance(artifact, dict)
                or set(artifact) != {"artifact_id", "path", "sha256"}
                or not isinstance(artifact["artifact_id"], str)
                or not artifact["artifact_id"]
                or artifact["artifact_id"] in reference_ids
                or not isinstance(artifact["path"], str)
                or not artifact["path"]
                or not isinstance(artifact["sha256"], str)
                or len(artifact["sha256"]) != SHA256_HEX_LENGTH
            ):
                raise ValueError("implementation contract design artifact is invalid")
            reference_ids.add(artifact["artifact_id"])
            local_reference_ids.add(artifact["artifact_id"])
            local_reference_sha256[artifact["artifact_id"]] = artifact["sha256"]
        for state in states:
            expected_keys = {
                "state_id",
                "name",
                "setup",
                "reference_artifact_id",
                "viewport",
                "anchors",
                "regions",
                "typography",
                "colors",
                "assets",
            }
            if not isinstance(state, dict) or set(state) != expected_keys:
                raise ValueError("implementation contract design state is incomplete")
            viewport = state["viewport"]
            if (
                not isinstance(state["state_id"], str)
                or not state["state_id"]
                or state["state_id"] in state_ids
                or not isinstance(state["name"], str)
                or not state["name"]
                or not isinstance(state["setup"], str)
                or not state["setup"].strip()
                or state["reference_artifact_id"] not in local_reference_ids
                or not isinstance(viewport, dict)
                or set(viewport) != {
                    "width",
                    "height",
                    "density",
                    "font_scale",
                    "locale",
                    "theme",
                    "system_bars",
                    "animations_disabled",
                }
                or not isinstance(state["anchors"], list)
                or not state["anchors"]
                or not isinstance(state["regions"], list)
                or not state["regions"]
                or any(
                    not isinstance(state[field], list)
                    for field in ("typography", "colors", "assets")
                )
            ):
                raise ValueError("implementation contract design state is incomplete")
            if (
                type(viewport["width"]) is not int
                or viewport["width"] <= 0
                or type(viewport["height"]) is not int
                or viewport["height"] <= 0
                or not isinstance(viewport["density"], (int, float))
                or viewport["density"] <= 0
                or not isinstance(viewport["font_scale"], (int, float))
                or viewport["font_scale"] <= 0
                or any(
                    not isinstance(viewport[field], str) or not viewport[field]
                    for field in ("locale", "theme", "system_bars")
                )
                or viewport["animations_disabled"] is not True
            ):
                raise ValueError("implementation contract design state is incomplete")
            anchor_names: set[str] = set()
            for anchor in state["anchors"]:
                if (
                    not isinstance(anchor, dict)
                    or set(anchor) != {"name", "expected", "tolerance"}
                    or not isinstance(anchor["name"], str)
                    or not anchor["name"]
                    or anchor["name"] in anchor_names
                    or not isinstance(anchor["expected"], (int, float))
                    or isinstance(anchor["expected"], bool)
                    or not isinstance(anchor["tolerance"], (int, float))
                    or isinstance(anchor["tolerance"], bool)
                    or anchor["tolerance"] < 0
                ):
                    raise ValueError("implementation contract design state is incomplete")
                anchor_names.add(anchor["name"])
            region_names: set[str] = set()
            for region in state["regions"]:
                if (
                    not isinstance(region, dict)
                    or set(region) != {"name", "max_mismatch_ratio"}
                    or not isinstance(region["name"], str)
                    or not region["name"]
                    or region["name"] in region_names
                    or not isinstance(region["max_mismatch_ratio"], (int, float))
                    or isinstance(region["max_mismatch_ratio"], bool)
                    or not 0 <= region["max_mismatch_ratio"] <= 1
                ):
                    raise ValueError("implementation contract design state is incomplete")
                region_names.add(region["name"])
            for entry in state["typography"]:
                if (
                    not isinstance(entry, dict)
                    or set(entry) != {"name", "properties"}
                    or not isinstance(entry["name"], str)
                    or not entry["name"]
                    or not isinstance(entry["properties"], dict)
                    or not entry["properties"]
                ):
                    raise ValueError("implementation contract design state is incomplete")
            for entry in state["colors"]:
                if (
                    not isinstance(entry, dict)
                    or set(entry) != {"name", "value"}
                    or not isinstance(entry["name"], str)
                    or not entry["name"]
                    or not isinstance(entry["value"], str)
                    or not entry["value"]
                ):
                    raise ValueError("implementation contract design state is incomplete")
            for entry in state["assets"]:
                if (
                    not isinstance(entry, dict)
                    or set(entry) != {"name", "artifact_id", "content_sha256"}
                    or not isinstance(entry["name"], str)
                    or not entry["name"]
                    or entry["artifact_id"] not in local_reference_ids
                    or not isinstance(entry["content_sha256"], str)
                    or len(entry["content_sha256"]) != SHA256_HEX_LENGTH
                    or local_reference_sha256.get(entry["artifact_id"])
                    != entry["content_sha256"]
                ):
                    raise ValueError("implementation contract design state is incomplete")
            state_ids.add(state["state_id"])
    if set(page_ids) != implemented_page_ids or len(page_ids) != len(implemented_page_ids):
        raise ValueError("every implemented page requires a design state contract")
    return design_contracts


def validate_observable_clauses(
    observable_clauses: object,
    *,
    source_clauses: list[object],
    execution_dag: list[object],
    design_contracts: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not isinstance(observable_clauses, list) or not observable_clauses:
        raise ValueError("implementation contract observable clauses are invalid")
    source_by_id: dict[str, dict[str, object]] = {}
    for source in source_clauses:
        if not isinstance(source, dict) or not isinstance(source.get("clause_id"), str):
            raise ValueError("implementation contract source clauses are invalid")
        if source["clause_id"] in source_by_id:
            raise ValueError("implementation contract source clauses are invalid")
        source_by_id[source["clause_id"]] = source
    owner_by_page: dict[str, str] = {}
    node_ids: set[str] = set()
    for node in execution_dag:
        if not isinstance(node, dict) or not isinstance(node.get("node_id"), str):
            raise ValueError("implementation contract ownership is invalid")
        node_ids.add(node["node_id"])
        if node.get("type") == "page":
            for page_id in node.get("page_ids", []):
                owner_by_page[str(page_id)] = node["node_id"]
    design_state_ids = {
        str(state["state_id"])
        for design in design_contracts
        for state in design["states"]
        if isinstance(state, dict)
    }
    observed_source_ids: list[str] = []
    observable_ids: set[str] = set()
    covered_design_state_ids: set[str] = set()
    expected_keys = {
        "clause_id",
        "page_id",
        "owner_node_id",
        "clause_type",
        "source_clause_ids",
        "preconditions",
        "action",
        "expected_observables",
        "forbidden_effects",
        "required_evidence",
        "design_state_ids",
    }
    types_by_source_kind = {
        "interface": {"interface"},
        "design": {"visual"},
        "behavior": {"behavior"},
        "requirement": {"interface", "behavior", "visual"},
        "acceptance": {"behavior", "visual"},
    }
    for clause in observable_clauses:
        if not isinstance(clause, dict) or set(clause) != expected_keys:
            raise ValueError("implementation contract observable clause is invalid")
        clause_id = clause["clause_id"]
        page_id = clause["page_id"]
        owner_node_id = clause["owner_node_id"]
        source_ids = clause["source_clause_ids"]
        if (
            not isinstance(clause_id, str)
            or not clause_id
            or clause_id in observable_ids
            or not isinstance(page_id, str)
            or page_id not in owner_by_page
            or owner_node_id != owner_by_page[page_id]
            or owner_node_id not in node_ids
            or not isinstance(source_ids, list)
            or not source_ids
            or len(set(source_ids)) != len(source_ids)
        ):
            raise ValueError("implementation contract observable clause is invalid")
        sources: list[dict[str, object]] = []
        for source_id in source_ids:
            source = source_by_id.get(str(source_id))
            if source is None or source.get("page_id") != page_id:
                raise ValueError("implementation contract source coverage mismatch")
            sources.append(source)
            observed_source_ids.append(str(source_id))
        allowed_type_sets = [
            types_by_source_kind.get(str(source.get("source_kind")), set())
            for source in sources
        ]
        allowed_types = (
            set.intersection(*allowed_type_sets) if allowed_type_sets else set()
        )
        if clause["clause_type"] not in allowed_types:
            source_kinds = sorted(
                {str(source.get("source_kind")) for source in sources}
            )
            raise ValueError(
                "implementation contract observable clause type is invalid: "
                f"clause_id={clause_id}; source_kinds={','.join(source_kinds)}; "
                f"allowed={','.join(sorted(allowed_types)) or 'none'}; "
                f"actual={clause['clause_type']}"
            )
        for field in ("preconditions", "expected_observables"):
            values = clause[field]
            if (
                not isinstance(values, list)
                or not values
                or any(not isinstance(value, str) or not value.strip() for value in values)
            ):
                raise ValueError("implementation contract observable clause is invalid")
        if not isinstance(clause["action"], str) or not clause["action"].strip():
            raise ValueError("implementation contract observable clause is invalid")
        forbidden_effects = clause["forbidden_effects"]
        if not isinstance(forbidden_effects, list) or any(
            not isinstance(value, str) or not value.strip() for value in forbidden_effects
        ):
            raise ValueError("implementation contract observable clause is invalid")
        required_evidence = clause["required_evidence"]
        if (
            not isinstance(required_evidence, list)
            or not required_evidence
            or len(set(required_evidence)) != len(required_evidence)
            or any(value not in EVIDENCE_KINDS for value in required_evidence)
        ):
            raise ValueError("observable clause required evidence is incomplete")
        minimum_evidence = {
            str(value)
            for source in sources
            for value in source.get("required_evidence", [])
        }
        source_kinds = {str(source["source_kind"]) for source in sources}
        if source_kinds & {"behavior", "requirement", "acceptance"}:
            minimum_evidence.add("integration")
        if "design" in source_kinds:
            minimum_evidence.add("visual")
        if clause["clause_type"] == "visual":
            minimum_evidence.add("visual")
        if not minimum_evidence.issubset(set(required_evidence)):
            raise ValueError(
                "observable clause required evidence is incomplete: "
                f"clause_id={clause_id}; "
                f"minimum={','.join(sorted(minimum_evidence))}; "
                f"actual={','.join(sorted(required_evidence))}"
            )
        state_ids = clause["design_state_ids"]
        if (
            not isinstance(state_ids, list)
            or len(set(state_ids)) != len(state_ids)
            or any(value not in design_state_ids for value in state_ids)
            or clause["clause_type"] == "visual"
            and not state_ids
        ):
            raise ValueError("implementation contract design state binding is invalid")
        if clause["clause_type"] == "visual":
            covered_design_state_ids.update(str(value) for value in state_ids)
        observable_ids.add(clause_id)
    if set(observed_source_ids) != set(source_by_id) or len(observed_source_ids) != len(
        source_by_id
    ):
        raise ValueError("implementation contract source coverage mismatch")
    if covered_design_state_ids != design_state_ids:
        raise ValueError("implementation contract design state coverage mismatch")
    return observable_clauses


def validate_acceptance_cases(
    acceptance_cases: object,
    *,
    observable_clauses: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not isinstance(acceptance_cases, list):
        raise ValueError("implementation contract acceptance cases are invalid")
    clauses = {str(clause["clause_id"]): clause for clause in observable_clauses}
    executable_levels = {"unit", "integration", "e2e"}
    required_pairs = {
        (clause_id, str(level))
        for clause_id, clause in clauses.items()
        for level in clause["required_evidence"]
        if level in executable_levels
    }
    covered_pairs: set[tuple[str, str]] = set()
    case_ids: set[str] = set()
    expected_keys = {
        "case_id",
        "clause_ids",
        "level",
        "preconditions",
        "action",
        "expected_observables",
    }
    for case in acceptance_cases:
        if not isinstance(case, dict) or set(case) != expected_keys:
            raise ValueError("implementation contract acceptance case is invalid")
        case_id = case["case_id"]
        level = case["level"]
        clause_ids = case["clause_ids"]
        if (
            not isinstance(case_id, str)
            or not case_id
            or case_id in case_ids
            or level not in executable_levels
            or not isinstance(clause_ids, list)
            or not clause_ids
            or len(set(clause_ids)) != len(clause_ids)
        ):
            raise ValueError("implementation contract acceptance case is invalid")
        for clause_id in clause_ids:
            clause = clauses.get(str(clause_id))
            if clause is None or level not in clause["required_evidence"]:
                raise ValueError("implementation contract acceptance case is invalid")
            covered_pairs.add((str(clause_id), str(level)))
        for field in ("preconditions", "expected_observables"):
            values = case[field]
            if (
                not isinstance(values, list)
                or not values
                or any(not isinstance(value, str) or not value.strip() for value in values)
            ):
                raise ValueError("implementation contract acceptance case is invalid")
        if not isinstance(case["action"], str) or not case["action"].strip():
            raise ValueError("implementation contract acceptance case is invalid")
        case_ids.add(case_id)
    if covered_pairs != required_pairs:
        raise ValueError("implementation contract acceptance coverage mismatch")
    return acceptance_cases


def validate_tdd_slices(
    tdd_slices: object,
    *,
    observable_clauses: list[dict[str, object]],
    acceptance_cases: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not isinstance(tdd_slices, list):
        raise ValueError("implementation contract TDD slices are invalid")
    clauses = {str(clause["clause_id"]): clause for clause in observable_clauses}
    integration_cases = {
        str(case["case_id"]): case
        for case in acceptance_cases
        if case["level"] == "integration"
    }
    covered_cases: list[str] = []
    slice_ids: set[str] = set()
    expected_keys = {
        "slice_id",
        "owner_node_id",
        "clause_ids",
        "integration_case_ids",
        "red_contract",
        "green_scope",
    }
    for item in tdd_slices:
        if not isinstance(item, dict) or set(item) != expected_keys:
            raise ValueError("implementation contract TDD slice is invalid")
        slice_id = item["slice_id"]
        clause_ids = item["clause_ids"]
        case_ids = item["integration_case_ids"]
        if (
            not isinstance(slice_id, str)
            or not slice_id
            or slice_id in slice_ids
            or not isinstance(clause_ids, list)
            or not clause_ids
            or len(set(clause_ids)) != len(clause_ids)
            or not isinstance(case_ids, list)
            or not case_ids
            or len(set(case_ids)) != len(case_ids)
            or not isinstance(item["red_contract"], str)
            or not item["red_contract"].strip()
            or not isinstance(item["green_scope"], str)
            or not item["green_scope"].strip()
        ):
            raise ValueError("implementation contract TDD slice is invalid")
        owners = {
            clauses[str(clause_id)]["owner_node_id"]
            for clause_id in clause_ids
            if str(clause_id) in clauses
        }
        if (
            len(owners) != 1
            or item["owner_node_id"] not in owners
            or any(str(clause_id) not in clauses for clause_id in clause_ids)
        ):
            raise ValueError("implementation contract TDD slice is invalid")
        for case_id in case_ids:
            case = integration_cases.get(str(case_id))
            if case is None or not set(case["clause_ids"]).issubset(set(clause_ids)):
                raise ValueError("implementation contract TDD slice is invalid")
            covered_cases.append(str(case_id))
        slice_ids.add(slice_id)
    if set(covered_cases) != set(integration_cases) or len(covered_cases) != len(
        integration_cases
    ):
        raise ValueError("implementation contract TDD coverage mismatch")
    return tdd_slices


def validate_interfaces_and_ownership(
    public_interfaces: object,
    ownership: object,
    *,
    execution_dag: list[object],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if not isinstance(public_interfaces, list) or not isinstance(ownership, list):
        raise ValueError("implementation contract ownership mismatch")
    expected_ownership = [
        {"node_id": node["node_id"], "allowed_paths": node["allowed_paths"]}
        for node in execution_dag
        if isinstance(node, dict)
    ]
    if ownership != expected_ownership:
        raise ValueError("implementation contract ownership mismatch")
    node_ids = [str(item["node_id"]) for item in expected_ownership]
    interface_owners: list[str] = []
    interface_ids: set[str] = set()
    for interface in public_interfaces:
        if not isinstance(interface, dict) or set(interface) != {
            "interface_id",
            "owner_node_id",
            "public_target",
            "inputs",
            "outputs",
        }:
            raise ValueError("implementation contract public interfaces are invalid")
        if (
            not isinstance(interface["interface_id"], str)
            or not interface["interface_id"]
            or interface["interface_id"] in interface_ids
            or interface["owner_node_id"] not in node_ids
            or not isinstance(interface["public_target"], str)
            or not interface["public_target"].strip()
            or not isinstance(interface["inputs"], list)
            or not isinstance(interface["outputs"], list)
        ):
            raise ValueError("implementation contract public interfaces are invalid")
        interface_ids.add(interface["interface_id"])
        interface_owners.append(str(interface["owner_node_id"]))
    if sorted(interface_owners) != sorted(node_ids):
        raise ValueError("implementation contract public interfaces are invalid")
    return public_interfaces, ownership


def validate_contract_envelope(
    contract: object,
    *,
    compiler_input: dict[str, object],
) -> dict[str, object]:
    required_keys = {
        "kind",
        "schema_version",
        "job_id",
        "job_digest",
        "compiler_input_digest",
        "source_clauses_digest",
        "public_interfaces",
        "ownership",
        "design_contracts",
        "observable_clauses",
        "acceptance_cases",
        "tdd_slices",
        "untested_boundaries",
    }
    if not isinstance(contract, dict) or set(contract) not in {
        frozenset(required_keys),
        frozenset({*required_keys, "context_source_clauses"}),
    }:
        raise ValueError("implementation contract envelope is invalid")
    if (
        contract["kind"] != "icp.implementation-contract.v1"
        or contract["schema_version"] != 1
        or contract["job_id"] != compiler_input.get("job_id")
        or contract["job_digest"] != compiler_input.get("job_digest")
        or contract["compiler_input_digest"] != digest(compiler_input)
        or contract["source_clauses_digest"]
        != compiler_input.get("source_clauses_digest")
    ):
        raise ValueError("implementation contract identity mismatch")
    boundaries = contract["untested_boundaries"]
    if not isinstance(boundaries, list) or any(
        not isinstance(value, str) or not value.strip() for value in boundaries
    ):
        raise ValueError("implementation contract untested boundaries are invalid")
    return contract
