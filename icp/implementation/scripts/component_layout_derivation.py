#!/usr/bin/env python3
"""Pure component-bound layout derivation.

This module deliberately has no dependency on the ICP stage runners.  It accepts
one closed Stage-2-style component page and returns a deterministic layout
contract.  Wiring it into a stage is a separate, reviewed change.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import defaultdict
from typing import Any, Callable


JSON = dict[str, Any]
LayoutSelector = Callable[[JSON], list[JSON]]
MAX_CONTAINER_DEPTH = 512
MAX_GRAPH_DEPTH = 256


class LayoutContractError(ValueError):
    """A closed contract or deterministic layout invariant was violated."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        self.code = code
        self.details = details
        if details:
            try:
                rendered_details = _canonical(details)
            except (TypeError, ValueError, RecursionError):
                try:
                    rendered_details = repr(details)
                except RecursionError:
                    rendered_details = "<details too deep>"
            suffix = f" details={rendered_details}"
        else:
            suffix = ""
        super().__init__(f"{code}: {message}{suffix}")


def _canonical(value: Any) -> str:
    if _container_depth_exceeded(value):
        raise ValueError("canonical value exceeds nesting limit")

    def normalize(item: Any) -> Any:
        if isinstance(item, float):
            if item == 0:
                return 0
            if item.is_integer():
                return int(item)
            return item
        if isinstance(item, dict):
            return {key: normalize(child) for key, child in item.items()}
        if isinstance(item, list):
            return [normalize(child) for child in item]
        return item

    return json.dumps(normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _container_depth_exceeded(value: Any, maximum_depth: int = MAX_CONTAINER_DEPTH) -> bool:
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > maximum_depth:
            return True
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    return False


def _stable_id(prefix: str, value: Any) -> str:
    digest = hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _fail(code: str, message: str, **details: Any) -> None:
    raise LayoutContractError(code, message, **details)


def _finite_number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def _validate_rect(value: Any, *, owner: str) -> JSON:
    if not isinstance(value, dict) or set(value) != {"left", "top", "width", "height"}:
        _fail("source_frame_invalid", "frame must contain left, top, width, and height", owner=owner)
    if not all(_finite_number(value[key]) for key in ("left", "top", "width", "height")):
        _fail("source_frame_invalid", "frame values must be finite numbers", owner=owner)
    if value["width"] < 0 or value["height"] < 0:
        _fail("source_frame_invalid", "frame width and height must be non-negative", owner=owner)
    return copy.deepcopy(value)


def _right(value: JSON) -> float:
    return value["left"] + value["width"]


def _bottom(value: JSON) -> float:
    return value["top"] + value["height"]


def _union_rects(values: list[JSON]) -> JSON:
    if not values:
        _fail("geometry_union_empty", "cannot build a geometry envelope without regions")
    left = min(value["left"] for value in values)
    top = min(value["top"] for value in values)
    right = max(_right(value) for value in values)
    bottom = max(_bottom(value) for value in values)
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}


def _translate_rect(value: JSON, left: float, top: float) -> JSON:
    return {
        "left": value["left"] - left,
        "top": value["top"] - top,
        "width": value["width"],
        "height": value["height"],
    }


def _intersection(first: JSON, second: JSON) -> JSON | None:
    left = max(first["left"], second["left"])
    top = max(first["top"], second["top"])
    right = min(_right(first), _right(second))
    bottom = min(_bottom(first), _bottom(second))
    if right <= left or bottom <= top:
        return None
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}


def _rect_relation(parent: JSON, child: JSON) -> str:
    contained = (
        child["left"] >= parent["left"]
        and child["top"] >= parent["top"]
        and _right(child) <= _right(parent)
        and _bottom(child) <= _bottom(parent)
    )
    if contained:
        return "contained"
    if _intersection(parent, child) is not None:
        return "overflow_or_overlay"
    return "detached_or_decoration"


def _selected_source_frame(node: JSON) -> JSON | None:
    basis = node.get("geometry_basis")
    if basis == "not_applicable":
        return None
    if basis == "frame":
        raw = node.get("frame")
    elif basis == "real_frame":
        raw = node.get("real_frame")
    elif basis == "combined":
        candidates = [
            _validate_rect(node[key], owner=node.get("source_node_id", "unknown"))
            for key in ("frame", "real_frame")
            if node.get(key) is not None
        ]
        if not candidates:
            _fail(
                "source_geometry_basis_invalid",
                "combined geometry needs frame or real_frame",
                source_node_id=node.get("source_node_id"),
            )
        return _union_rects(candidates)
    else:
        _fail(
            "source_geometry_basis_invalid",
            "geometry_basis must be frame, real_frame, combined, or not_applicable",
            source_node_id=node.get("source_node_id"),
            geometry_basis=basis,
        )
    if raw is None:
        _fail(
            "source_geometry_basis_invalid",
            "selected geometry basis is missing its frame",
            source_node_id=node.get("source_node_id"),
            geometry_basis=basis,
        )
    return _validate_rect(raw, owner=node.get("source_node_id", "unknown"))


def _slot_definitions(page: JSON) -> dict[str, dict[str, JSON]]:
    result: dict[str, dict[str, JSON]] = {}
    definitions = page.get("component_definitions_by_id")
    if not isinstance(definitions, dict):
        _fail("component_definitions_invalid", "component definitions must be a map")
    for component_id, definition in definitions.items():
        if not isinstance(definition, dict) or definition.get("component_id") != component_id:
            _fail("component_definitions_invalid", "component definition identity mismatch", component_id=component_id)
        raw_slots = definition.get("slots", [])
        if not isinstance(raw_slots, list):
            _fail("component_definitions_invalid", "component slots must be a list", component_id=component_id)
        slots: dict[str, JSON] = {}
        for slot in raw_slots:
            slot_id = slot.get("slot_id") if isinstance(slot, dict) else None
            if not isinstance(slot_id, str) or not slot_id or slot_id in slots:
                _fail("component_slot_invalid", "slot identity must be non-empty and unique", component_id=component_id)
            if slot.get("cardinality") not in {"one", "optional", "many"}:
                _fail("component_slot_invalid", "slot cardinality is unsupported", component_id=component_id, slot=slot_id)
            slots[slot_id] = copy.deepcopy(slot)
        result[component_id] = slots
    return result


def _validate_and_build_tree(page: JSON) -> JSON:
    forbidden = {
        "raw_rows",
        "source_bundle",
        "interaction_description",
        "ui_description",
        "codebase_reuse",
    }
    leaked: list[str] = []
    stack: list[tuple[str, Any]] = [("$", page)]
    while stack:
        path, value = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}"
                if key in forbidden:
                    leaked.append(child_path)
                stack.append((child_path, child))
        elif isinstance(value, list):
            stack.extend((f"{path}[{index}]", child) for index, child in enumerate(value))
    leaked.sort()
    if leaked:
        _fail("stage_boundary_violation", "layout input contains upstream or codebase-owned data", paths=leaked)

    instances = page.get("instances")
    root_id = page.get("root_instance_id")
    if not isinstance(instances, list) or not isinstance(root_id, str) or not root_id:
        _fail("component_tree_invalid", "instances and root_instance_id are required")
    nodes: dict[str, JSON] = {}
    for raw in instances:
        instance_id = raw.get("instance_id") if isinstance(raw, dict) else None
        if not isinstance(instance_id, str) or not instance_id or instance_id in nodes:
            _fail("component_tree_invalid", "instance identity must be non-empty and unique", instance_id=instance_id)
        if not isinstance(raw.get("slot"), str) or not raw["slot"]:
            _fail("component_tree_invalid", "every component instance, including root, needs a non-empty slot", instance_id=instance_id)
        nodes[instance_id] = copy.deepcopy(raw)
    if root_id not in nodes:
        _fail("component_tree_invalid", "root instance does not exist", root_instance_id=root_id)
    if nodes[root_id].get("parent_instance_id") is not None:
        _fail("component_tree_invalid", "root parent must be null", root_instance_id=root_id)

    slot_defs = _slot_definitions(page)
    children: dict[str, dict[str, list[JSON]]] = defaultdict(lambda: defaultdict(list))
    for instance_id, node in nodes.items():
        component_id = node.get("component_id")
        if component_id not in slot_defs:
            _fail("component_tree_invalid", "instance references an unknown component", instance_id=instance_id, component_id=component_id)
        order = node.get("order")
        if not isinstance(order, int) or isinstance(order, bool) or order < 0:
            _fail("sibling_order_invalid", "order must be a non-negative integer", instance_id=instance_id, order=order)
        blocks = node.get("source_block_ids")
        if not isinstance(blocks, list) or any(not isinstance(value, str) or not value for value in blocks):
            _fail("block_ownership_invalid", "source_block_ids must be a string list", instance_id=instance_id)
        if instance_id == root_id:
            continue
        parent_id = node.get("parent_instance_id")
        if parent_id not in nodes:
            _fail("component_tree_invalid", "instance parent does not exist", instance_id=instance_id, parent_instance_id=parent_id)
        slot = node.get("slot")
        parent_component = nodes[parent_id].get("component_id")
        if slot not in slot_defs[parent_component]:
            _fail("component_slot_invalid", "instance slot is not declared by its parent component", instance_id=instance_id, parent_instance_id=parent_id, slot=slot)
        children[parent_id][slot].append(node)

    for parent_id, by_slot in children.items():
        parent_component = nodes[parent_id]["component_id"]
        for slot, group in by_slot.items():
            ordered = sorted(group, key=lambda value: value["order"])
            actual = [value["order"] for value in ordered]
            expected = list(range(len(ordered)))
            if actual != expected:
                _fail("sibling_order_invalid", "sibling order must be unique and contiguous", parent_instance_id=parent_id, slot=slot, expected=expected, actual=actual)
            cardinality = slot_defs[parent_component][slot]["cardinality"]
            if cardinality == "one" and len(ordered) != 1:
                _fail("component_slot_invalid", "required one slot must have exactly one child", parent_instance_id=parent_id, slot=slot, count=len(ordered))
            if cardinality == "optional" and len(ordered) > 1:
                _fail("component_slot_invalid", "optional slot cannot have multiple children", parent_instance_id=parent_id, slot=slot, count=len(ordered))
            children[parent_id][slot] = ordered

    for parent_id, parent in nodes.items():
        component_slots = slot_defs[parent["component_id"]]
        for slot, definition in component_slots.items():
            if definition["cardinality"] == "one" and len(children.get(parent_id, {}).get(slot, [])) != 1:
                _fail(
                    "component_slot_invalid",
                    "required one slot must have exactly one child",
                    parent_instance_id=parent_id,
                    slot=slot,
                    count=len(children.get(parent_id, {}).get(slot, [])),
                )

    state: dict[str, str] = {}
    stack: list[tuple[str, bool, int]] = [(root_id, False, 0)]
    while stack:
        instance_id, exiting, depth = stack.pop()
        if depth > MAX_GRAPH_DEPTH:
            _fail(
                "component_tree_too_deep",
                "component tree exceeds the execution depth limit",
                maximum_depth=MAX_GRAPH_DEPTH,
            )
        if exiting:
            state[instance_id] = "done"
            continue
        if state.get(instance_id) == "visiting":
            _fail("component_tree_invalid", "component tree contains a cycle", instance_id=instance_id)
        if state.get(instance_id) == "done":
            continue
        state[instance_id] = "visiting"
        stack.append((instance_id, True, depth))
        descendants = [
            child["instance_id"]
            for group in children.get(instance_id, {}).values()
            for child in group
        ]
        stack.extend((child_id, False, depth + 1) for child_id in reversed(descendants))
    visited = {instance_id for instance_id, value in state.items() if value == "done"}
    if visited != set(nodes):
        _fail("component_tree_invalid", "component tree contains unreachable instances", unreachable=sorted(set(nodes) - visited))

    normalized_children = {
        parent_id: {
            slot: [value["instance_id"] for value in group]
            for slot, group in sorted(by_slot.items())
        }
        for parent_id, by_slot in sorted(children.items())
    }
    return {
        "root_instance_id": root_id,
        "nodes_by_instance_id": {key: nodes[key] for key in sorted(nodes)},
        "children_by_parent_and_slot": normalized_children,
    }


def _validate_block_ownership(page: JSON, tree: JSON) -> dict[str, str]:
    blocks = page.get("blocks_by_id")
    if not isinstance(blocks, dict):
        _fail("block_ownership_invalid", "blocks_by_id must be a map")
    owners: dict[str, list[str]] = defaultdict(list)
    for instance_id, instance in tree["nodes_by_instance_id"].items():
        for block_id in instance["source_block_ids"]:
            owners[block_id].append(instance_id)
    unknown = sorted(set(owners) - set(blocks))
    if unknown:
        _fail("block_ownership_invalid", "instances reference unknown Blocks", block_ids=unknown)
    invalid = {block_id: owners.get(block_id, []) for block_id in sorted(blocks) if len(owners.get(block_id, [])) != 1}
    if invalid:
        _fail("block_ownership_invalid", "every page Block must have exactly one owner", ownership=invalid)
    return {block_id: values[0] for block_id, values in owners.items()}


def _resolve_artboard_frames(page: JSON) -> dict[str, JSON | None]:
    reference = page.get("reference")
    nodes = page.get("source_nodes_by_id")
    if not isinstance(reference, dict) or not isinstance(nodes, dict):
        _fail("source_coordinate_contract_invalid", "reference and source_nodes_by_id are required")
    root_id = reference.get("root_source_node_id")
    logical_size = reference.get("logical_artboard_size")
    contract = reference.get("coordinate_contract")
    if root_id not in nodes or not isinstance(logical_size, dict) or not isinstance(contract, dict):
        _fail("source_coordinate_contract_invalid", "root, logical size, and coordinate contract are required")
    if set(logical_size) != {"width", "height"}:
        _fail("source_coordinate_contract_invalid", "logical artboard size must contain only width and height")
    supported = contract.get("supported_frame_spaces")
    if (
        not isinstance(supported, list)
        or any(not isinstance(value, str) for value in supported)
        or set(supported) != {"canvas", "artboard", "parent"}
    ):
        _fail("source_coordinate_contract_invalid", "coordinate contract must declare canvas, artboard, and parent modes")
    if not _finite_number(logical_size.get("width")) or not _finite_number(logical_size.get("height")):
        _fail("source_coordinate_contract_invalid", "logical artboard size must be finite")

    prepared: dict[str, tuple[JSON, JSON | None]] = {}
    seen_orders: dict[int, str] = {}
    for node_id, node in nodes.items():
        if not isinstance(node, dict) or node.get("source_node_id") != node_id:
            _fail("source_node_invalid", "source node identity mismatch", source_node_id=node_id)
        order = node.get("source_order")
        if not isinstance(order, int) or isinstance(order, bool) or order < 0 or order in seen_orders:
            _fail("source_order_invalid", "source_order must be a unique non-negative integer", source_node_id=node_id, source_order=order)
        seen_orders[order] = node_id
        selected = _selected_source_frame(node)
        if selected is not None and node.get("frame_space") not in supported:
            _fail("source_frame_space_invalid", "framed source node needs one supported frame_space", source_node_id=node_id, frame_space=node.get("frame_space"))
        prepared[node_id] = (node, selected)

    for start_id in prepared:
        chain: set[str] = set()
        node_id: str | None = start_id
        depth = 0
        while node_id is not None:
            if depth > MAX_GRAPH_DEPTH:
                _fail(
                    "source_parent_too_deep",
                    "source parent graph exceeds the execution depth limit",
                    source_node_id=start_id,
                    maximum_depth=MAX_GRAPH_DEPTH,
                )
            if node_id in chain:
                _fail(
                    "source_coordinate_cycle",
                    "source parent graph contains a cycle",
                    source_node_id=node_id,
                )
            if node_id not in prepared:
                _fail(
                    "source_parent_invalid",
                    "source node parent does not exist",
                    source_node_id=start_id,
                    source_parent_node_id=node_id,
                )
            chain.add(node_id)
            node_id = prepared[node_id][0].get("source_parent_node_id")
            depth += 1

    if any(
        selected is not None and node.get("frame_space") == "canvas"
        for node, selected in prepared.values()
    ) and prepared[root_id][0].get("frame_space") != "canvas":
        _fail(
            "source_frame_space_invalid",
            "canvas-space source nodes require a canvas-space root",
            root_source_node_id=root_id,
            root_frame_space=prepared[root_id][0].get("frame_space"),
        )

    root_raw = prepared[root_id][1]
    if root_raw is None:
        _fail("source_coordinate_contract_invalid", "root source node must have geometry", root_source_node_id=root_id)
    if root_raw["width"] != logical_size["width"] or root_raw["height"] != logical_size["height"]:
        _fail("source_coordinate_contract_invalid", "root source size must equal logical artboard size", root_frame=root_raw, logical_artboard_size=logical_size)

    memo: dict[str, JSON | None] = {}
    visiting: set[str] = set()

    def resolve(node_id: str) -> JSON | None:
        if node_id in memo:
            return memo[node_id]
        if node_id in visiting:
            _fail("source_coordinate_cycle", "parent-local source geometry contains a cycle", source_node_id=node_id)
        visiting.add(node_id)
        node, selected = prepared[node_id]
        if selected is None:
            value = None
        elif node_id == root_id:
            value = {"left": 0, "top": 0, "width": selected["width"], "height": selected["height"]}
        elif node["frame_space"] == "artboard":
            value = copy.deepcopy(selected)
        elif node["frame_space"] == "canvas":
            value = {
                "left": selected["left"] - root_raw["left"],
                "top": selected["top"] - root_raw["top"],
                "width": selected["width"],
                "height": selected["height"],
            }
        else:
            parent_id = node.get("source_parent_node_id")
            if parent_id not in prepared:
                _fail("source_parent_invalid", "parent-local source node has no resolvable parent", source_node_id=node_id, source_parent_node_id=parent_id)
            parent = resolve(parent_id)
            if parent is None:
                _fail("source_parent_invalid", "parent-local source node parent has no geometry", source_node_id=node_id, source_parent_node_id=parent_id)
            value = {
                "left": parent["left"] + selected["left"],
                "top": parent["top"] + selected["top"],
                "width": selected["width"],
                "height": selected["height"],
            }
        memo[node_id] = value
        visiting.remove(node_id)
        return value

    for _, node_id in sorted((order, node_id) for order, node_id in seen_orders.items()):
        resolve(node_id)
    return {node_id: memo[node_id] for node_id in sorted(memo)}


def _build_block_geometry(page: JSON, frames: dict[str, JSON | None]) -> dict[str, JSON]:
    result: dict[str, JSON] = {}
    allowed_roles = {"static_visual", "static_copy", "dynamic_content", "platform_element"}
    source_memberships: dict[str, list[str]] = defaultdict(list)
    known_source_node_ids = set(page["source_nodes_by_id"])
    for block_id, block in page["blocks_by_id"].items():
        if not isinstance(block, dict) or block.get("block_id") != block_id:
            _fail("block_geometry_invalid", "Block identity mismatch", block_id=block_id)
        ordered = block.get("ordered_source_node_ids")
        rendering = block.get("rendering_source_node_ids")
        non_rendering = block.get("non_rendering_source_node_ids")
        roles = block.get("content_roles_by_source_node_id")
        if (
            not all(isinstance(value, list) for value in (ordered, rendering, non_rendering))
            or any(not isinstance(node_id, str) or not node_id for values in (ordered, rendering, non_rendering) for node_id in values)
            or not isinstance(roles, dict)
            or any(not isinstance(node_id, str) or not node_id for node_id in roles)
        ):
            _fail("block_geometry_invalid", "Block source membership is incomplete", block_id=block_id)
        if (
            len(ordered) != len(set(ordered))
            or len(rendering) != len(set(rendering))
            or len(non_rendering) != len(set(non_rendering))
            or set(rendering).intersection(non_rendering)
            or set(ordered) != set(rendering).union(non_rendering)
        ):
            _fail("block_geometry_invalid", "Block source membership is not a lossless partition", block_id=block_id)
        if set(roles) != set(ordered):
            _fail("block_geometry_invalid", "every Block source node needs a content role", block_id=block_id)
        invalid_roles = {
            node_id: role
            for node_id, role in roles.items()
            if not isinstance(role, str) or role not in allowed_roles
        }
        if invalid_roles:
            _fail(
                "content_role_invalid",
                "content roles must use the closed geometry-policy vocabulary",
                block_id=block_id,
                invalid_roles=invalid_roles,
                allowed_roles=sorted(allowed_roles),
            )
        semantic_parent = block.get("semantic_parent_block_id")
        if semantic_parent is not None and semantic_parent not in page["blocks_by_id"]:
            _fail(
                "semantic_parent_block_invalid",
                "semantic parent Block must exist on the same page",
                block_id=block_id,
                semantic_parent_block_id=semantic_parent,
            )
        if semantic_parent == block_id:
            _fail(
                "semantic_parent_block_invalid",
                "Block cannot be its own semantic parent",
                block_id=block_id,
            )
        unknown = sorted(set(ordered) - known_source_node_ids)
        if unknown:
            _fail("block_geometry_invalid", "Block references unknown source nodes", block_id=block_id, source_node_ids=unknown)
        for node_id in ordered:
            source_memberships[node_id].append(block_id)
        rendering_set = set(rendering)
        boundary_nodes = [
            node_id
            for node_id in ordered
            if node_id in rendering_set
            and frames[node_id] is not None
            and page["source_nodes_by_id"][node_id].get("source_parent_node_id") not in rendering_set
        ]
        visual = bool(rendering)
        if visual and not boundary_nodes:
            _fail("block_geometry_invalid", "visual Block has no boundary geometry", block_id=block_id)
        regions = [
            {"source_node_id": node_id, "rect": copy.deepcopy(frames[node_id])}
            for node_id in boundary_nodes
        ]
        rendering_regions = [
            {"source_node_id": node_id, "rect": copy.deepcopy(frames[node_id])}
            for node_id in ordered
            if node_id in rendering_set and frames[node_id] is not None
        ]
        result[block_id] = {
            "boundary_source_node_ids": boundary_nodes,
            "boundary_regions": regions,
            "artboard_envelope": _union_rects([value["rect"] for value in regions]) if regions else None,
            "rendering_regions": rendering_regions,
            "visual_envelope": _union_rects([value["rect"] for value in rendering_regions]) if rendering_regions else None,
        }
    invalid_memberships = {
        node_id: source_memberships.get(node_id, [])
        for node_id in sorted(page["source_nodes_by_id"])
        if len(source_memberships.get(node_id, [])) != 1
    }
    if invalid_memberships:
        _fail(
            "source_node_block_ownership_invalid",
            "every projected source node must belong to exactly one semantic Block",
            source_node_memberships=invalid_memberships,
        )

    for start_id in sorted(page["blocks_by_id"]):
        chain: set[str] = set()
        block_id: str | None = start_id
        depth = 0
        while block_id is not None:
            if depth > MAX_GRAPH_DEPTH:
                _fail(
                    "semantic_block_tree_too_deep",
                    "semantic Block parent graph exceeds the execution depth limit",
                    block_id=start_id,
                    maximum_depth=MAX_GRAPH_DEPTH,
                )
            if block_id in chain:
                _fail(
                    "semantic_parent_block_invalid",
                    "semantic Block parent graph contains a cycle",
                    block_id=block_id,
                )
            if block_id not in page["blocks_by_id"]:
                _fail(
                    "semantic_parent_block_invalid",
                    "semantic Block parent does not exist",
                    block_id=start_id,
                    parent_block_id=block_id,
                )
            chain.add(block_id)
            block_id = page["blocks_by_id"][block_id].get("semantic_parent_block_id")
            depth += 1
    return result


def _root_first(tree: JSON) -> list[str]:
    result: list[str] = []
    stack = [tree["root_instance_id"]]
    while stack:
        instance_id = stack.pop()
        result.append(instance_id)
        descendants = [
            child_id
            for _, child_ids in tree["children_by_parent_and_slot"].get(instance_id, {}).items()
            for child_id in child_ids
        ]
        stack.extend(reversed(descendants))
    return result


def _build_component_geometry(page: JSON, tree: JSON, owners: dict[str, str], block_geometry: dict[str, JSON]) -> dict[str, JSON]:
    result: dict[str, JSON] = {}
    logical_size = page["reference"]["logical_artboard_size"]
    root_id = tree["root_instance_id"]
    traversal = _root_first(tree)
    for instance_id in traversal:
        instance = tree["nodes_by_instance_id"][instance_id]
        owned_regions = [
            {"block_id": block_id, **copy.deepcopy(region)}
            for block_id in instance["source_block_ids"]
            for region in block_geometry[block_id]["rendering_regions"]
        ]
        if instance_id == root_id:
            boundary_blocks = [
                block_id
                for block_id in instance["source_block_ids"]
                if page["blocks_by_id"][block_id].get("semantic_parent_block_id") is None
                or owners.get(page["blocks_by_id"][block_id].get("semantic_parent_block_id")) != instance_id
            ]
            root_source_node_id = page["reference"]["root_source_node_id"]
            root_source_blocks = [
                block_id
                for block_id in boundary_blocks
                if root_source_node_id in page["blocks_by_id"][block_id]["ordered_source_node_ids"]
            ]
            if len(root_source_blocks) != 1:
                _fail(
                    "component_geometry_invalid",
                    "root source node must resolve to exactly one root-owned Block",
                    root_source_node_id=root_source_node_id,
                    block_ids=root_source_blocks,
                )
            regions = [
                {
                    "block_id": root_source_blocks[0],
                    "source_node_id": root_source_node_id,
                    "rect": {"left": 0, "top": 0, "width": logical_size["width"], "height": logical_size["height"]},
                }
            ]
            envelope = copy.deepcopy(regions[0]["rect"])
            geometry_source = "root_artboard"
        else:
            boundary_blocks = [
                block_id
                for block_id in instance["source_block_ids"]
                if page["blocks_by_id"][block_id].get("semantic_parent_block_id") is None
                or owners.get(page["blocks_by_id"][block_id].get("semantic_parent_block_id")) != instance_id
            ]
            regions = []
            for block_id in boundary_blocks:
                for region in block_geometry[block_id]["boundary_regions"]:
                    regions.append({"block_id": block_id, **copy.deepcopy(region)})
            envelope = _union_rects([value["rect"] for value in owned_regions]) if owned_regions else None
            geometry_source = "bound_blocks" if envelope is not None else "none"
        result[instance_id] = {
            "instance_id": instance_id,
            "boundary_block_ids": boundary_blocks,
            "boundary_regions": regions,
            "owned_regions": owned_regions,
            "artboard_envelope": envelope,
            "geometry_source": geometry_source,
        }

    for instance_id in reversed(traversal):
        if result[instance_id]["artboard_envelope"] is not None:
            continue
        child_envelopes = [
            result[child_id]["artboard_envelope"]
            for child_ids in tree["children_by_parent_and_slot"].get(instance_id, {}).values()
            for child_id in child_ids
            if result[child_id]["artboard_envelope"] is not None
        ]
        if child_envelopes:
            result[instance_id]["artboard_envelope"] = _union_rects(child_envelopes)
            result[instance_id]["geometry_source"] = "descendant_union"

    for instance_id in traversal:
        envelope = result[instance_id]["artboard_envelope"]
        regions = result[instance_id]["boundary_regions"]
        if envelope is None:
            local_envelope = None
            local_regions = []
        elif instance_id == root_id:
            local_envelope = copy.deepcopy(envelope)
            local_regions = copy.deepcopy(regions)
        else:
            parent_id = tree["nodes_by_instance_id"][instance_id]["parent_instance_id"]
            parent_envelope = result[parent_id]["artboard_envelope"]
            if parent_envelope is None:
                _fail(
                    "component_geometry_invalid",
                    "component geometry cannot be localized through a parent without derived geometry",
                    instance_id=instance_id,
                    parent_instance_id=parent_id,
                )
            local_envelope = _translate_rect(envelope, parent_envelope["left"], parent_envelope["top"])
            local_regions = [
                {
                    **{key: value for key, value in region.items() if key != "rect"},
                    "rect": _translate_rect(region["rect"], parent_envelope["left"], parent_envelope["top"]),
                }
                for region in regions
            ]
        result[instance_id]["local_regions"] = local_regions
        result[instance_id]["local_envelope"] = local_envelope
    return result


def _instance_source_refs(page: JSON, tree: JSON, instance_id: str) -> JSON:
    instance = tree["nodes_by_instance_id"][instance_id]
    source_ids: list[str] = []
    for block_id in instance["source_block_ids"]:
        source_ids.extend(page["blocks_by_id"][block_id]["ordered_source_node_ids"])
    unique = list(dict.fromkeys(source_ids))
    return {"block_ids": list(instance["source_block_ids"]), "source_node_ids": unique}


def _instance_paint_refs(
    page: JSON,
    tree: JSON,
    instance_id: str,
    memo: dict[str, JSON] | None = None,
) -> JSON:
    if memo is None:
        memo = {}
    if instance_id in memo:
        return memo[instance_id]
    instance = tree["nodes_by_instance_id"][instance_id]
    block_ids: list[str] = []
    source_ids: list[str] = []
    for block_id in instance["source_block_ids"]:
        rendering = page["blocks_by_id"][block_id]["rendering_source_node_ids"]
        if rendering:
            block_ids.append(block_id)
            source_ids.extend(rendering)
    if not source_ids:
        for child_ids in tree["children_by_parent_and_slot"].get(instance_id, {}).values():
            for child_id in child_ids:
                child_refs = _instance_paint_refs(page, tree, child_id, memo)
                block_ids.extend(child_refs["block_ids"])
                source_ids.extend(child_refs["source_node_ids"])
    result = {
        "block_ids": list(dict.fromkeys(block_ids)),
        "source_node_ids": list(dict.fromkeys(source_ids)),
    }
    memo[instance_id] = result
    return result


def _overlapping_pairs(member_ids: list[str], geometry: dict[str, JSON]) -> list[tuple[str, str]]:
    positioned = [
        (instance_id, geometry[instance_id]["artboard_envelope"])
        for instance_id in member_ids
        if geometry[instance_id]["artboard_envelope"] is not None
    ]
    positioned = [
        value
        for value in positioned
        if value[1]["width"] > 0 and value[1]["height"] > 0
    ]
    order = {instance_id: index for index, instance_id in enumerate(member_ids)}

    def peak_concurrency(axis: str) -> int:
        start_key, end = ("left", _right) if axis == "x" else ("top", _bottom)
        events = [
            event
            for _, rectangle in positioned
            for event in ((rectangle[start_key], 1), (end(rectangle), -1))
        ]
        active_count = 0
        peak = 0
        for _, delta in sorted(events, key=lambda value: (value[0], value[1])):
            active_count += delta
            peak = max(peak, active_count)
        return peak

    axis = "x" if peak_concurrency("x") <= peak_concurrency("y") else "y"
    start_key, end = ("left", _right) if axis == "x" else ("top", _bottom)
    secondary_key = "top" if axis == "x" else "left"
    positioned.sort(key=lambda value: (value[1][start_key], value[1][secondary_key], order[value[0]]))
    active: list[tuple[str, JSON]] = []
    overlaps: list[tuple[str, str]] = []
    for current_id, current_rect in positioned:
        active = [value for value in active if end(value[1]) > current_rect[start_key]]
        for previous_id, previous_rect in active:
            if _intersection(previous_rect, current_rect) is not None:
                if order[previous_id] < order[current_id]:
                    overlaps.append((previous_id, current_id))
                else:
                    overlaps.append((current_id, previous_id))
        active.append((current_id, current_rect))
    return sorted(overlaps, key=lambda pair: (order[pair[0]], order[pair[1]]))


def _append_evidence(values: list[JSON], payload: JSON) -> None:
    payload = copy.deepcopy(payload)
    payload["evidence_id"] = _stable_id("layout-evidence", payload)
    values.append(payload)


def _relation_payload(first: JSON, second: JSON) -> JSON:
    return {
        "horizontal_gap": second["left"] - _right(first),
        "vertical_gap": second["top"] - _bottom(first),
        "overlap": _intersection(first, second),
        "shared_leading_edge": first["left"] == second["left"],
        "shared_trailing_edge": _right(first) == _right(second),
        "shared_horizontal_center": first["left"] + first["width"] / 2 == second["left"] + second["width"] / 2,
        "shared_top_edge": first["top"] == second["top"],
        "shared_bottom_edge": _bottom(first) == _bottom(second),
    }


def _derive_layout_evidence(page: JSON, tree: JSON, geometry: dict[str, JSON]) -> list[JSON]:
    evidence: list[JSON] = []
    nodes = tree["nodes_by_instance_id"]
    source_nodes = page["source_nodes_by_id"]
    source_refs_by_instance = {
        instance_id: _instance_source_refs(page, tree, instance_id)
        for instance_id in _root_first(tree)
    }
    paint_ref_memo: dict[str, JSON] = {}

    for parent_id in _root_first(tree):
        parent_rect = geometry[parent_id]["artboard_envelope"]
        by_slot = tree["children_by_parent_and_slot"].get(parent_id, {})
        for slot, child_ids in by_slot.items():
            for child_id in child_ids:
                child_rect = geometry[child_id]["artboard_envelope"]
                if parent_rect is None or child_rect is None:
                    continue
                child = nodes[child_id]
                local_rect = geometry[child_id]["local_envelope"]
                _append_evidence(
                    evidence,
                    {
                        "kind": "parent_child",
                        "parent_instance_id": parent_id,
                        "child_instance_id": child_id,
                        "slot": slot,
                        "order": child["order"],
                        "local_rect": copy.deepcopy(geometry[child_id]["local_envelope"]),
                        "containment": _rect_relation(parent_rect, child_rect),
                        "leading_inset": child_rect["left"] - parent_rect["left"],
                        "top_inset": child_rect["top"] - parent_rect["top"],
                        "trailing_inset": _right(parent_rect) - _right(child_rect),
                        "bottom_inset": _bottom(parent_rect) - _bottom(child_rect),
                        "local_left": local_rect["left"],
                        "local_top": local_rect["top"],
                        "child_width": child_rect["width"],
                        "child_height": child_rect["height"],
                        "source_references": copy.deepcopy(source_refs_by_instance[child_id]),
                    },
                )
            for previous_id, current_id in zip(child_ids, child_ids[1:]):
                previous_rect = geometry[previous_id]["artboard_envelope"]
                current_rect = geometry[current_id]["artboard_envelope"]
                if previous_rect is None or current_rect is None:
                    continue
                _append_evidence(
                    evidence,
                    {
                        "kind": "sibling_relation",
                        "parent_instance_id": parent_id,
                        "slot": slot,
                        "previous_instance_id": previous_id,
                        "current_instance_id": current_id,
                        "order_relation": nodes[previous_id]["order"] < nodes[current_id]["order"],
                        **_relation_payload(previous_rect, current_rect),
                        "source_references": {
                            "previous": copy.deepcopy(source_refs_by_instance[previous_id]),
                            "current": copy.deepcopy(source_refs_by_instance[current_id]),
                        },
                    },
                )

        occupied_slots = list(by_slot)
        for first_index, first_slot in enumerate(occupied_slots):
            for second_slot in occupied_slots[first_index + 1 :]:
                for first_id in by_slot[first_slot]:
                    for second_id in by_slot[second_slot]:
                        first_rect = geometry[first_id]["artboard_envelope"]
                        second_rect = geometry[second_id]["artboard_envelope"]
                        if first_rect is None or second_rect is None:
                            continue
                        _append_evidence(
                            evidence,
                            {
                                "kind": "cross_slot_relation",
                                "parent_instance_id": parent_id,
                                "first_slot": first_slot,
                                "second_slot": second_slot,
                                "first_instance_id": first_id,
                                "second_instance_id": second_id,
                                **_relation_payload(first_rect, second_rect),
                                "source_references": {
                                    "first": copy.deepcopy(source_refs_by_instance[first_id]),
                                    "second": copy.deepcopy(source_refs_by_instance[second_id]),
                                },
                            },
                        )

        all_children = [child_id for child_ids in by_slot.values() for child_id in child_ids]
        paint_refs = {
            child_id: _instance_paint_refs(page, tree, child_id, paint_ref_memo)
            for child_id in all_children
        }
        paint_orders = {
            child_id: min(
                (source_nodes[value]["source_order"] for value in paint_refs[child_id]["source_node_ids"]),
                default=None,
            )
            for child_id in all_children
        }
        for first_id, second_id in _overlapping_pairs(all_children, geometry):
            first_order = paint_orders[first_id]
            second_order = paint_orders[second_id]
            if first_order is None or second_order is None:
                painted_later = None
            else:
                painted_later = second_id if second_order > first_order else first_id
            _append_evidence(
                evidence,
                {
                    "kind": "source_paint_order",
                    "parent_instance_id": parent_id,
                    "first_instance_id": first_id,
                    "second_instance_id": second_id,
                    "first_source_order": first_order,
                    "second_source_order": second_order,
                    "painted_later_instance_id": painted_later,
                    "overlap": _intersection(
                        geometry[first_id]["artboard_envelope"],
                        geometry[second_id]["artboard_envelope"],
                    ),
                    "source_references": {
                        "first": copy.deepcopy(paint_refs[first_id]),
                        "second": copy.deepcopy(paint_refs[second_id]),
                    },
                },
            )
    return evidence


def _initial_dimension_policy(page: JSON, tree: JSON) -> dict[str, JSON]:
    result: dict[str, JSON] = {}
    root_id = tree["root_instance_id"]
    for instance_id in reversed(_root_first(tree)):
        instance = tree["nodes_by_instance_id"][instance_id]
        roles = {
            role
            for block_id in instance["source_block_ids"]
            for role in page["blocks_by_id"][block_id]["content_roles_by_source_node_id"].values()
        }
        child_ids = [
            child_id
            for values in tree["children_by_parent_and_slot"].get(instance_id, {}).values()
            for child_id in values
        ]
        child_runtime_variable = any(
            result[child_id][dimension]["runtime"] != "intrinsic"
            for child_id in child_ids
            for dimension in ("width", "height")
        )
        if instance_id == root_id:
            policy = {
                "x": {"reference": "exact_origin", "runtime": "viewport_origin"},
                "y": {"reference": "exact_origin", "runtime": "viewport_origin"},
                "width": {"reference": "exact", "runtime": "viewport_constraint"},
                "height": {"reference": "viewport", "runtime": "viewport_and_scroll_content"},
            }
        elif roles.intersection({"static_copy", "dynamic_content"}):
            policy = {
                "x": {"reference": "exact", "runtime": "reference_relation"},
                "y": {"reference": "exact", "runtime": "reference_relation"},
                "width": {"reference": "exact", "runtime": "constraint_driven"},
                "height": {"reference": "measured_only", "runtime": "content_driven"},
            }
        elif roles and roles.issubset({"static_visual", "platform_element"}) and not child_runtime_variable:
            policy = {
                "x": {"reference": "exact", "runtime": "reference_relation"},
                "y": {"reference": "exact", "runtime": "reference_relation"},
                "width": {"reference": "exact", "runtime": "intrinsic"},
                "height": {"reference": "exact", "runtime": "intrinsic"},
            }
        else:
            policy = {
                "x": {"reference": "exact", "runtime": "reference_relation"},
                "y": {"reference": "exact", "runtime": "reference_relation"},
                "width": {"reference": "exact", "runtime": "constraint_driven"},
                "height": {
                    "reference": "measured_only" if child_runtime_variable else "exact",
                    "runtime": "content_driven" if child_runtime_variable else "constraint_driven",
                },
            }
        result[instance_id] = policy
    return result


def _validate_constraint_target(target: Any, decision: JSON, member_instances: list[str]) -> None:
    if not isinstance(target, dict) or not isinstance(target.get("kind"), str):
        _fail("constraint_target_invalid", "constraint target must use the closed object grammar", target=target)
    kind = target["kind"]
    member_set = set(member_instances)
    if kind in {"position", "size"}:
        if (
            set(target) != {"kind", "instance_id", "axis"}
            or not isinstance(target.get("instance_id"), str)
            or not isinstance(target.get("axis"), str)
            or target.get("axis") not in {"x", "y"}
        ):
            _fail("constraint_target_invalid", "position and size targets need instance_id and x/y axis", target=target)
        if target["instance_id"] not in member_set:
            _fail("constraint_target_invalid", "constraint target instance is outside the decision", target=target)
        if kind == "position" and decision["layout_kind"] not in {"overlay", "constraint"}:
            _fail(
                "constraint_position_invalid",
                "ordinary flow/grid/scroll layout cannot pin a member to an absolute position",
                decision_id=decision["decision_id"],
                target=target,
            )
        return
    if kind == "gap":
        required = {"kind", "axis", "previous_instance_id", "current_instance_id"}
        if (
            set(target) != required
            or not all(isinstance(target.get(key), str) for key in required)
            or target.get("axis") not in {"horizontal", "vertical"}
        ):
            _fail("constraint_target_invalid", "gap target has invalid fields", target=target)
        if target["previous_instance_id"] not in member_set or target["current_instance_id"] not in member_set:
            _fail("constraint_target_invalid", "gap target members are outside the decision", target=target)
        return
    if kind == "inset":
        required = {"kind", "instance_id", "edge"}
        if (
            set(target) != required
            or not all(isinstance(target.get(key), str) for key in required)
            or target.get("edge") not in {"leading", "top", "trailing", "bottom"}
        ):
            _fail("constraint_target_invalid", "inset target has invalid fields", target=target)
        if target["instance_id"] not in member_set:
            _fail("constraint_target_invalid", "inset target instance is outside the decision", target=target)
        return
    if kind == "overlap":
        required = {"kind", "first_instance_id", "second_instance_id"}
        if set(target) != required or not all(isinstance(target.get(key), str) for key in required):
            _fail("constraint_target_invalid", "overlap target has invalid fields", target=target)
        if target["first_instance_id"] not in member_set or target["second_instance_id"] not in member_set:
            _fail("constraint_target_invalid", "overlap target members are outside the decision", target=target)
        return
    _fail("constraint_target_invalid", "constraint target kind is not in the closed grammar", target=target)


def _decision_obligations(tree: JSON, evidence: list[JSON]) -> list[JSON]:
    obligations: list[JSON] = []
    evidence_by_parent: dict[str, list[JSON]] = defaultdict(list)
    for value in evidence:
        parent_id = value.get("parent_instance_id")
        if isinstance(parent_id, str):
            evidence_by_parent[parent_id].append(value)
    for parent_id in _root_first(tree):
        by_slot = tree["children_by_parent_and_slot"].get(parent_id, {})
        parent_evidence = evidence_by_parent.get(parent_id, [])
        for slot, child_ids in by_slot.items():
            identity = {"scope": "slot", "parent_instance_id": parent_id, "slot": slot}
            relevant = [
                value["evidence_id"]
                for value in parent_evidence
                if (
                    value.get("slot") == slot
                    or value.get("child_instance_id") in child_ids
                    or (
                        value.get("kind") == "source_paint_order"
                        and value.get("first_instance_id") in child_ids
                        and value.get("second_instance_id") in child_ids
                    )
                )
            ]
            obligations.append(
                {
                    "decision_id": _stable_id("layout-decision", identity),
                    **identity,
                    "member_ids": list(child_ids),
                    "evidence_ids": list(dict.fromkeys(relevant)),
                }
            )
        if len(by_slot) > 1:
            identity = {"scope": "slots", "parent_instance_id": parent_id, "slot": None}
            relevant = [
                value["evidence_id"]
                for value in parent_evidence
                if value["kind"] in {"cross_slot_relation", "source_paint_order"}
            ]
            obligations.append(
                {
                    "decision_id": _stable_id("layout-decision", identity),
                    **identity,
                    "member_ids": list(by_slot),
                    "evidence_ids": list(dict.fromkeys(relevant)),
                }
            )
    return obligations


def _evaluate_expression(expression: Any, evidence_by_id: dict[str, JSON]) -> Any:
    if not isinstance(expression, dict) or "op" not in expression:
        _fail("constraint_expression_invalid", "constraint expression must be an object with an op")
    op = expression["op"]
    if not isinstance(op, str):
        _fail("constraint_expression_invalid", "constraint op must be a string", expression=expression)
    if op == "copy":
        if set(expression) != {"op", "evidence_id", "field"}:
            _fail("constraint_expression_invalid", "copy expression has unknown or missing fields", expression=expression)
        if not isinstance(expression["evidence_id"], str) or not isinstance(expression["field"], str):
            _fail("constraint_expression_invalid", "copy evidence_id and field must be strings", expression=expression)
        evidence = evidence_by_id.get(expression["evidence_id"])
        if evidence is None or expression["field"] not in evidence:
            _fail("constraint_evidence_invalid", "copy expression references missing evidence data", expression=expression)
        value = evidence[expression["field"]]
        if not (_finite_number(value) or isinstance(value, bool) or value is None or isinstance(value, dict)):
            _fail("constraint_expression_invalid", "copy expression resolved to an unsupported value", expression=expression)
        return copy.deepcopy(value)
    if op in {"add", "subtract", "min", "max"}:
        if set(expression) != {"op", "args"} or not isinstance(expression["args"], list) or len(expression["args"]) < 2:
            _fail("constraint_expression_invalid", f"{op} expression needs at least two args", expression=expression)
        values = [_evaluate_expression(value, evidence_by_id) for value in expression["args"]]
        if not all(_finite_number(value) for value in values):
            _fail("constraint_expression_invalid", f"{op} expression requires numeric evidence", expression=expression)
        if op == "add":
            return sum(values)
        if op == "subtract":
            head, *tail = values
            return head - sum(tail)
        return min(values) if op == "min" else max(values)
    if op == "nearest_gap":
        if (
            set(expression) != {"op", "evidence_ids", "axis"}
            or not isinstance(expression["evidence_ids"], list)
            or not expression["evidence_ids"]
            or any(not isinstance(value, str) for value in expression["evidence_ids"])
            or not isinstance(expression["axis"], str)
            or expression["axis"] not in {"horizontal", "vertical"}
        ):
            _fail("constraint_expression_invalid", "nearest_gap expression has invalid fields", expression=expression)
        field = f"{expression['axis']}_gap"
        values = []
        for evidence_id in expression["evidence_ids"]:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None or not _finite_number(evidence.get(field)):
                _fail("constraint_evidence_invalid", "nearest_gap references missing gap evidence", expression=expression)
            values.append(evidence[field])
        if not values:
            _fail("constraint_expression_invalid", "nearest_gap needs evidence", expression=expression)
        return min(values, key=lambda value: abs(value))
    if op == "union":
        if (
            set(expression) != {"op", "evidence_ids", "field"}
            or not isinstance(expression["evidence_ids"], list)
            or not expression["evidence_ids"]
            or any(not isinstance(value, str) for value in expression["evidence_ids"])
            or not isinstance(expression["field"], str)
        ):
            _fail("constraint_expression_invalid", "union expression has invalid fields", expression=expression)
        values = []
        for evidence_id in expression["evidence_ids"]:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None or not isinstance(evidence.get(expression["field"]), dict):
                _fail("constraint_evidence_invalid", "union references missing rectangle evidence", expression=expression)
            try:
                rectangle = _validate_rect(
                    evidence[expression["field"]],
                    owner=f"constraint:{evidence_id}:{expression['field']}",
                )
            except LayoutContractError:
                _fail(
                    "constraint_evidence_invalid",
                    "union evidence field is not a rectangle",
                    evidence_id=evidence_id,
                    field=expression["field"],
                )
            values.append(rectangle)
        return _union_rects(values)
    _fail("constraint_expression_invalid", "constraint op is not in the closed grammar", op=op)


def _expression_evidence_ids(expression: Any) -> set[str]:
    if not isinstance(expression, dict):
        return set()
    result: set[str] = set()
    if isinstance(expression.get("evidence_id"), str):
        result.add(expression["evidence_id"])
    if isinstance(expression.get("evidence_ids"), list):
        result.update(value for value in expression["evidence_ids"] if isinstance(value, str))
    for arg in expression.get("args", []) if isinstance(expression.get("args"), list) else []:
        result.update(_expression_evidence_ids(arg))
    return result


def _validate_expression_depth(expression: Any, *, maximum_depth: int = 64) -> None:
    stack: list[tuple[Any, int]] = [(expression, 0)]
    while stack:
        value, depth = stack.pop()
        if depth > maximum_depth:
            _fail(
                "constraint_expression_too_deep",
                "constraint expression exceeds the supported nesting depth",
                maximum_depth=maximum_depth,
            )
        if not isinstance(value, dict):
            continue
        args = value.get("args")
        if isinstance(args, list):
            stack.extend((child, depth + 1) for child in args)


def _evidence_pair(value: JSON) -> tuple[str, str] | None:
    if value.get("kind") == "sibling_relation":
        return value.get("previous_instance_id"), value.get("current_instance_id")
    if value.get("kind") in {"cross_slot_relation", "source_paint_order"}:
        return value.get("first_instance_id"), value.get("second_instance_id")
    return None


def _expression_leaves(expression: JSON) -> list[JSON]:
    if expression["op"] in {"add", "subtract", "min", "max"}:
        return [leaf for arg in expression["args"] for leaf in _expression_leaves(arg)]
    return [expression]


def _validate_expression_target_binding(
    target: JSON,
    expression: JSON,
    evidence_by_id: dict[str, JSON],
    resolved: Any,
) -> None:
    leaves = _expression_leaves(expression)
    target_kind = target["kind"]
    expected_pair: tuple[str, str] | None = None
    expected_instance: str | None = None
    expected_fields: set[str] = set()
    expected_type = "number"
    if target_kind == "gap":
        expected_pair = (target["previous_instance_id"], target["current_instance_id"])
        expected_fields = {f"{target['axis']}_gap"}
    elif target_kind == "inset":
        expected_instance = target["instance_id"]
        expected_fields = {
            {
                "leading": "leading_inset",
                "top": "top_inset",
                "trailing": "trailing_inset",
                "bottom": "bottom_inset",
            }[target["edge"]]
        }
    elif target_kind == "size":
        expected_instance = target["instance_id"]
        expected_fields = {"child_width" if target["axis"] == "x" else "child_height"}
    elif target_kind == "position":
        expected_instance = target["instance_id"]
        expected_fields = {"local_left" if target["axis"] == "x" else "local_top"}
    elif target_kind == "overlap":
        expected_pair = (target["first_instance_id"], target["second_instance_id"])
        expected_fields = {"overlap"}
        expected_type = "rect"

    for leaf in leaves:
        op = leaf["op"]
        if op == "nearest_gap":
            if target_kind != "gap" or leaf["axis"] != target["axis"]:
                _fail("constraint_evidence_target_mismatch", "nearest_gap does not match its target", target=target, expression=leaf)
            evidence_ids = leaf["evidence_ids"]
            fields = {f"{leaf['axis']}_gap"}
        elif op == "union":
            if target_kind != "overlap" or leaf["field"] != "overlap":
                _fail("constraint_evidence_target_mismatch", "union does not match its target", target=target, expression=leaf)
            evidence_ids = leaf["evidence_ids"]
            fields = {leaf["field"]}
        elif op == "copy":
            evidence_ids = [leaf["evidence_id"]]
            fields = {leaf["field"]}
        else:
            _fail("constraint_evidence_target_mismatch", "expression leaf is incompatible with target", target=target, expression=leaf)
        if fields != expected_fields:
            _fail(
                "constraint_evidence_target_mismatch",
                "expression field does not match constraint target",
                target=target,
                expression=leaf,
                expected_fields=sorted(expected_fields),
            )
        for evidence_id in evidence_ids:
            evidence = evidence_by_id[evidence_id]
            if expected_pair is not None and _evidence_pair(evidence) != expected_pair:
                _fail(
                    "constraint_evidence_target_mismatch",
                    "evidence component pair does not match constraint target",
                    target=target,
                    evidence_id=evidence_id,
                    evidence_pair=_evidence_pair(evidence),
                )
            if expected_instance is not None and (
                evidence.get("kind") != "parent_child"
                or evidence.get("child_instance_id") != expected_instance
            ):
                _fail(
                    "constraint_evidence_target_mismatch",
                    "evidence component does not match constraint target",
                    target=target,
                    evidence_id=evidence_id,
                )
    if expected_type == "number" and not _finite_number(resolved):
        _fail("constraint_result_type_invalid", "numeric geometry target requires a finite numeric result", target=target, resolved=resolved)
    if expected_type == "rect":
        try:
            _validate_rect(resolved, owner="constraint:overlap")
        except LayoutContractError:
            _fail("constraint_result_type_invalid", "overlap target requires a rectangle result", target=target, resolved=resolved)


def _validate_decisions(obligations: list[JSON], decisions: Any, evidence: list[JSON], initial_policy: dict[str, JSON], tree: JSON) -> list[JSON]:
    if not isinstance(decisions, list):
        _fail("layout_decisions_invalid", "layout selector must return a list")
    expected_by_id = {value["decision_id"]: value for value in obligations}
    if any(not isinstance(value, dict) or not isinstance(value.get("decision_id"), str) for value in decisions):
        _fail("layout_decisions_invalid", "every layout decision needs a string decision_id")
    actual_ids = [value["decision_id"] for value in decisions]
    if len(decisions) != len(expected_by_id) or len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != set(expected_by_id):
        _fail("layout_decisions_invalid", "layout decisions must cover every obligation exactly once", expected=sorted(expected_by_id), actual=actual_ids)
    allowed_keys = {
        "decision_id",
        "scope",
        "parent_instance_id",
        "slot",
        "ordered_member_ids",
        "layout_kind",
        "main_axis",
        "sizing_policy",
        "alignment_policy",
        "constraints",
        "overflow_policy",
        "evidence_ids",
        "rationale",
    }
    evidence_by_id = {value["evidence_id"]: value for value in evidence}
    normalized: list[JSON] = []
    for raw in decisions:
        if set(raw) != allowed_keys:
            _fail("layout_decision_schema_invalid", "layout decision has unknown or missing fields", decision_id=raw.get("decision_id"), expected=sorted(allowed_keys), actual=sorted(raw))
        obligation = expected_by_id[raw["decision_id"]]
        for key in ("scope", "parent_instance_id", "slot"):
            if raw[key] != obligation[key]:
                _fail("layout_decision_identity_invalid", "layout decision changed its frozen identity", decision_id=raw["decision_id"], field=key, expected=obligation[key], actual=raw[key])
        if not isinstance(raw["ordered_member_ids"], list) or any(
            not isinstance(value, str) for value in raw["ordered_member_ids"]
        ):
            _fail("layout_decision_schema_invalid", "ordered_member_ids must be a string list", decision_id=raw["decision_id"])
        if raw["scope"] == "slot":
            correct_members = raw["ordered_member_ids"] == obligation["member_ids"]
        else:
            correct_members = len(raw["ordered_member_ids"]) == len(set(raw["ordered_member_ids"])) and set(raw["ordered_member_ids"]) == set(obligation["member_ids"])
        if not correct_members:
            _fail("decision_members_invalid", "layout decision changed or omitted frozen members", decision_id=raw["decision_id"], expected=obligation["member_ids"], actual=raw["ordered_member_ids"])
        if not isinstance(raw["layout_kind"], str) or raw["layout_kind"] not in {"flow", "overlay", "grid", "scroll", "intrinsic", "platform", "constraint"}:
            _fail("layout_decision_schema_invalid", "layout_kind is unsupported", decision_id=raw["decision_id"])
        if not isinstance(raw["main_axis"], str) or raw["main_axis"] not in {"vertical", "horizontal", "none"}:
            _fail("layout_decision_schema_invalid", "main_axis is unsupported", decision_id=raw["decision_id"])
        if raw["layout_kind"] == "overlay" and raw["main_axis"] != "none":
            _fail("overlay_axis_invalid", "overlay layout cannot invent a flow axis", decision_id=raw["decision_id"])
        sizing = raw["sizing_policy"]
        if (
            not isinstance(sizing, dict)
            or set(sizing) != {"width", "height"}
            or not isinstance(sizing.get("width"), str)
            or not isinstance(sizing.get("height"), str)
            or sizing["width"] not in {"constraint", "content", "intrinsic", "fixed"}
            or sizing["height"] not in {"constraint", "content", "intrinsic", "fixed"}
        ):
            _fail("layout_decision_schema_invalid", "sizing_policy is invalid", decision_id=raw["decision_id"])
        member_instances = obligation["member_ids"] if raw["scope"] == "slot" else [
            child_id
            for slot in obligation["member_ids"]
            for child_id in tree["children_by_parent_and_slot"][raw["parent_instance_id"]][slot]
        ]
        if raw["layout_kind"] != "overlay" and len(member_instances) > 1 and raw["main_axis"] == "none":
            _fail(
                "layout_axis_required",
                "multi-member non-overlay layout requires a horizontal or vertical relation axis",
                decision_id=raw["decision_id"],
                instance_ids=member_instances,
            )
        # A decision sizes the members of its slot/group. The parent may own
        # unrelated copy or other content-driven geometry; that does not force
        # every child member to use content sizing.
        affected_instances = list(dict.fromkeys(member_instances))
        for decision_axis, policy_axis in (("height", "height"), ("width", "width")):
            content_driven = any(
                initial_policy[value][policy_axis]["runtime"] == "content_driven"
                for value in affected_instances
            )
            if content_driven and sizing[decision_axis] != "content":
                _fail(
                    "fixed_adaptive_dimension",
                    "content-driven dimension cannot be declared fixed, intrinsic, or constraint-only",
                    decision_id=raw["decision_id"],
                    axis=decision_axis,
                    sizing=sizing[decision_axis],
                    instance_ids=affected_instances,
                )
        if not isinstance(raw["overflow_policy"], str) or raw["overflow_policy"] not in {"reachable", "clip_decoration", "visible_overlay", "scroll"}:
            _fail("layout_decision_schema_invalid", "overflow_policy is unsupported", decision_id=raw["decision_id"])
        if not isinstance(raw["alignment_policy"], str) or raw["alignment_policy"] not in {
            "source_evidence",
            "leading",
            "center",
            "trailing",
            "stretch",
            "baseline",
        }:
            _fail("layout_decision_schema_invalid", "alignment_policy is unsupported", decision_id=raw["decision_id"])
        if not isinstance(raw["rationale"], str) or not raw["rationale"].strip():
            _fail("layout_decision_schema_invalid", "layout decision needs a rationale", decision_id=raw["decision_id"])
        if (
            not isinstance(raw["evidence_ids"], list)
            or any(not isinstance(value, str) for value in raw["evidence_ids"])
            or not set(raw["evidence_ids"]).issubset(evidence_by_id)
            or not set(raw["evidence_ids"]).issubset(set(obligation["evidence_ids"]))
        ):
            _fail("constraint_evidence_invalid", "layout decision cites unknown evidence", decision_id=raw["decision_id"])
        if raw["layout_kind"] == "overlay":
            cited = [evidence_by_id[value] for value in raw["evidence_ids"]]
            if not any(value.get("overlap") is not None for value in cited):
                _fail(
                    "overlay_evidence_required",
                    "overlay layout requires cited overlap evidence from the bound design state",
                    decision_id=raw["decision_id"],
                )
        if not isinstance(raw["constraints"], list):
            _fail("constraint_schema_invalid", "constraints must be a list", decision_id=raw["decision_id"])
        normalized_constraints = []
        for constraint in raw["constraints"]:
            if not isinstance(constraint, dict) or set(constraint) != {"target", "expression"}:
                _fail("constraint_schema_invalid", "exact constraints require target and evidence expression", decision_id=raw["decision_id"], constraint=constraint)
            _validate_constraint_target(constraint["target"], raw, member_instances)
            _validate_expression_depth(constraint["expression"])
            expression_evidence = _expression_evidence_ids(constraint["expression"])
            if not expression_evidence.issubset(set(raw["evidence_ids"])):
                _fail(
                    "constraint_evidence_invalid",
                    "constraint expression must cite evidence declared by its decision",
                    decision_id=raw["decision_id"],
                    expression_evidence=sorted(expression_evidence),
                    decision_evidence=sorted(raw["evidence_ids"]),
                )
            resolved = _evaluate_expression(constraint["expression"], evidence_by_id)
            _validate_expression_target_binding(
                constraint["target"],
                constraint["expression"],
                evidence_by_id,
                resolved,
            )
            normalized_constraints.append({**copy.deepcopy(constraint), "resolved_value": resolved})
        normalized.append({**copy.deepcopy(raw), "constraints": normalized_constraints})
    return sorted(normalized, key=lambda value: value["decision_id"])


def _propagate_dimension_policy(tree: JSON, initial: dict[str, JSON], decisions: list[JSON]) -> dict[str, JSON]:
    policies = copy.deepcopy(initial)
    by_identity = {(value["scope"], value["parent_instance_id"], value["slot"]): value for value in decisions}

    def propagate_group(parent_id: str, member_ids: list[str], axis: str) -> None:
        adaptive_seen = False
        for member_id in member_ids:
            if adaptive_seen and axis == "vertical":
                policies[member_id]["y"] = {"reference": "flow_relative", "runtime": "flow_relative"}
            if adaptive_seen and axis == "horizontal":
                policies[member_id]["x"] = {"reference": "flow_relative", "runtime": "flow_relative"}
            dimension = "height" if axis == "vertical" else "width"
            if policies[member_id][dimension]["runtime"] != "intrinsic":
                adaptive_seen = True
        if adaptive_seen and parent_id != tree["root_instance_id"]:
            dimension = "height" if axis == "vertical" else "width"
            policies[parent_id][dimension] = {
                "reference": "measured_only",
                "runtime": "content_driven",
            }

    for parent_id in reversed(_root_first(tree)):
        by_slot = tree["children_by_parent_and_slot"].get(parent_id, {})
        for slot, child_ids in by_slot.items():
            decision = by_identity[("slot", parent_id, slot)]
            if decision["main_axis"] in {"vertical", "horizontal"}:
                propagate_group(parent_id, child_ids, decision["main_axis"])
        slots_decision = by_identity.get(("slots", parent_id, None))
        if slots_decision and slots_decision["main_axis"] in {"vertical", "horizontal"}:
            groups = [
                child_id
                for slot in slots_decision["ordered_member_ids"]
                for child_id in by_slot[slot]
            ]
            propagate_group(parent_id, groups, slots_decision["main_axis"])
    return policies


def _build_assertions(
    page: JSON,
    tree: JSON,
    geometry: dict[str, JSON],
    policies: dict[str, JSON],
    evidence: list[JSON],
    decisions: list[JSON],
) -> tuple[list[JSON], list[JSON]]:
    reference: list[JSON] = []
    responsive: list[JSON] = []
    root_id = tree["root_instance_id"]
    logical_size = page["reference"]["logical_artboard_size"]
    reference.append({"kind": "root_reference_viewport", "instance_id": root_id, "expected": {"left": 0, "top": 0, **logical_size}})
    for instance_id, node in tree["nodes_by_instance_id"].items():
        topology = {
            "instance_id": instance_id,
            "parent_instance_id": node["parent_instance_id"],
            "slot": node["slot"],
            "order": node["order"],
        }
        reference.append({"kind": "component_topology", **topology})
        responsive.append({"kind": "component_topology", **topology})
        if geometry[instance_id]["artboard_envelope"] is not None:
            reference.append(
                {
                    "kind": "reference_geometry",
                    "instance_id": instance_id,
                    "expected": copy.deepcopy(geometry[instance_id]["artboard_envelope"]),
                    "dimension_policy": copy.deepcopy(policies[instance_id]),
                }
            )
        responsive.append(
            {
                "kind": "responsive_geometry",
                "instance_id": instance_id,
                "requires": ["positive_measured_bounds", "no_unintended_horizontal_overflow"],
            }
        )
        envelope = geometry[instance_id]["artboard_envelope"]
        if instance_id != root_id and envelope is not None:
            reference_viewport = {"left": 0, "top": 0, **logical_size}
            responsive.append(
                {
                    "kind": "horizontal_overflow_allowance",
                    "instance_id": instance_id,
                    "left": max(0, reference_viewport["left"] - envelope["left"]),
                    "right": max(0, _right(envelope) - _right(reference_viewport)),
                }
            )
            responsive.append(
                {
                    "kind": "vertical_clipping_allowance",
                    "instance_id": instance_id,
                    "top": max(0, reference_viewport["top"] - envelope["top"]),
                    "bottom": max(
                        0, _bottom(envelope) - _bottom(reference_viewport)
                    ),
                }
            )
    decisions_by_identity = {
        (value["scope"], value["parent_instance_id"], value["slot"]): value
        for value in decisions
    }
    cross_gap_boundaries: dict[tuple[str, frozenset[str]], tuple[str, str]] = {}
    for decision in decisions:
        if (
            decision["scope"] != "slots"
            or decision["main_axis"] not in {"vertical", "horizontal"}
            or decision["layout_kind"] == "overlay"
        ):
            continue
        parent_id = decision["parent_instance_id"]
        by_slot = tree["children_by_parent_and_slot"][parent_id]
        for previous_slot, current_slot in zip(
            decision["ordered_member_ids"],
            decision["ordered_member_ids"][1:],
        ):
            previous_id = by_slot[previous_slot][-1]
            current_id = by_slot[current_slot][0]
            cross_gap_boundaries[(parent_id, frozenset((previous_id, current_id)))] = (previous_id, current_id)

    for item in evidence:
        if item["kind"] == "sibling_relation":
            decision = decisions_by_identity[("slot", item["parent_instance_id"], item["slot"])]
            first_id = item["previous_instance_id"]
            second_id = item["current_instance_id"]
        elif item["kind"] == "cross_slot_relation":
            decision = decisions_by_identity.get(("slots", item["parent_instance_id"], None))
            if decision is None:
                continue
            first_id = item["first_instance_id"]
            second_id = item["second_instance_id"]
            boundary = cross_gap_boundaries.get(
                (item["parent_instance_id"], frozenset((first_id, second_id)))
            )
            if boundary is None:
                decision = None
            else:
                first_id, second_id = boundary
        elif item["kind"] == "source_paint_order":
            # Paint evidence covers every pair under the same component parent,
            # including non-consecutive members omitted from gap evidence.
            decision = None
            first_id = item["first_instance_id"]
            second_id = item["second_instance_id"]
        else:
            continue
        if decision is not None and decision["main_axis"] in {"vertical", "horizontal"} and decision["layout_kind"] != "overlay":
            axis = decision["main_axis"]
            relation = _relation_payload(
                geometry[first_id]["artboard_envelope"],
                geometry[second_id]["artboard_envelope"],
            )
            reference.append(
                {
                    "kind": "sibling_gap",
                    "relation_kind": item["kind"],
                    "evidence_id": item["evidence_id"],
                    "parent_instance_id": item["parent_instance_id"],
                    "previous_instance_id": first_id,
                    "current_instance_id": second_id,
                    "axis": axis,
                    "expected_gap": relation[f"{axis}_gap"],
                    "measurement": "after_natural_layout",
                }
            )

    for parent_id in _root_first(tree):
        member_ids = [
            child_id
            for child_ids in tree["children_by_parent_and_slot"].get(parent_id, {}).values()
            for child_id in child_ids
            if geometry[child_id]["artboard_envelope"] is not None
        ]
        if len(member_ids) < 2:
            continue
        responsive.append(
            {
                "kind": "no_unintended_overlap_group",
                "parent_instance_id": parent_id,
                "member_instance_ids": member_ids,
                "allowed_overlap_pairs": [list(pair) for pair in _overlapping_pairs(member_ids, geometry)],
            }
        )
    def subtree(instance_id: str) -> list[str]:
        values: list[str] = []
        pending = [instance_id]
        while pending:
            current = pending.pop()
            values.append(current)
            descendants = [
                child_id
                for child_ids in tree["children_by_parent_and_slot"].get(current, {}).values()
                for child_id in child_ids
            ]
            pending.extend(reversed(descendants))
        return values

    for decision in decisions:
        if decision["layout_kind"] != "scroll":
            continue
        if decision["scope"] == "slot":
            roots = decision["ordered_member_ids"]
        else:
            roots = [
                child_id
                for slot in decision["ordered_member_ids"]
                for child_id in tree["children_by_parent_and_slot"][decision["parent_instance_id"]][slot]
            ]
        allowed = list(dict.fromkeys(value for root in roots for value in subtree(root)))
        responsive.append(
            {
                "kind": "scroll_overflow_scope",
                "decision_id": decision["decision_id"],
                "axis": decision["main_axis"],
                "allowed_instance_ids": allowed,
            }
        )
        if decision["main_axis"] == "horizontal":
            responsive.append(
                {
                    "kind": "horizontal_overflow_scope",
                    "decision_id": decision["decision_id"],
                    "allowed_instance_ids": allowed,
                }
            )
    for decision in decisions:
        if decision["layout_kind"] == "scroll":
            responsive.append(
                {
                    "kind": "scroll_reachability",
                    "decision_id": decision["decision_id"],
                    "container_instance_id": decision["parent_instance_id"],
                    "axis": decision["main_axis"],
                }
            )
    return reference, responsive


def _build_audit_joins(page: JSON, tree: JSON, geometry: dict[str, JSON]) -> list[JSON]:
    joins: list[JSON] = []
    for instance_id in _root_first(tree):
        node = tree["nodes_by_instance_id"][instance_id]
        joins.append(
            {
                "instance_id": instance_id,
                "component_id": node["component_id"],
                "parent_instance_id": node["parent_instance_id"],
                "slot": node["slot"],
                "order": node["order"],
                "source_block_ids": list(node["source_block_ids"]),
                "boundary_source_node_ids": [value["source_node_id"] for value in geometry[instance_id]["boundary_regions"]],
                "owned_source_node_ids": [value["source_node_id"] for value in geometry[instance_id]["owned_regions"]],
            }
        )
    return joins


def _build_source_geometry_provenance(page: JSON, frames: dict[str, JSON | None]) -> dict[str, JSON]:
    return {
        node_id: {
            "source_node_id": node_id,
            "source_parent_node_id": node.get("source_parent_node_id"),
            "source_order": node["source_order"],
            "geometry_basis": node["geometry_basis"],
            "frame_space": node.get("frame_space"),
            "frame": copy.deepcopy(node.get("frame")),
            "real_frame": copy.deepcopy(node.get("real_frame")),
            "resolved_artboard_frame": copy.deepcopy(frames[node_id]),
        }
        for node_id, node in sorted(page["source_nodes_by_id"].items())
    }


def _prepare_component_layout(bound_page: JSON) -> dict[str, Any]:
    if not isinstance(bound_page, dict):
        _fail("layout_input_invalid", "bound component page must be an object")
    if _container_depth_exceeded(bound_page):
        _fail(
            "layout_input_too_deep",
            "bound component page exceeds the closed input nesting limit",
            maximum_depth=MAX_CONTAINER_DEPTH,
        )
    page = copy.deepcopy(bound_page)
    tree = _validate_and_build_tree(page)
    owners = _validate_block_ownership(page, tree)
    frames = _resolve_artboard_frames(page)
    block_geometry = _build_block_geometry(page, frames)
    component_geometry = _build_component_geometry(page, tree, owners, block_geometry)
    evidence = _derive_layout_evidence(page, tree, component_geometry)
    initial_policy = _initial_dimension_policy(page, tree)
    obligations = _decision_obligations(tree, evidence)
    selector_input = {
        "page_key": page.get("page_key"),
        "design_state_id": page.get("design_state_id"),
        "artboard_frames_by_source_node_id": copy.deepcopy(frames),
        "component_tree": copy.deepcopy(tree),
        "component_geometry_by_instance_id": copy.deepcopy(component_geometry),
        "layout_evidence": copy.deepcopy(evidence),
        "initial_dimension_policy_by_instance_id": copy.deepcopy(initial_policy),
        "component_definitions_by_id": copy.deepcopy(page["component_definitions_by_id"]),
        "platform_context": copy.deepcopy(page.get("platform_context", {})),
        "decision_obligations": copy.deepcopy(obligations),
    }
    return {
        "page": page,
        "tree": tree,
        "frames": frames,
        "block_geometry": block_geometry,
        "component_geometry": component_geometry,
        "evidence": evidence,
        "initial_policy": initial_policy,
        "obligations": obligations,
        "selector_input": selector_input,
    }


def prepare_component_layout_selection(bound_page: JSON) -> JSON:
    """Return the exact closed model input before any layout decision is authored."""

    return copy.deepcopy(_prepare_component_layout(bound_page)["selector_input"])


def derive_component_layout(bound_page: JSON, model_layout_selector: LayoutSelector) -> JSON:
    """Derive one closed layout contract without mutating or joining upstream data."""

    if not callable(model_layout_selector):
        _fail("layout_selector_invalid", "model_layout_selector must be callable")
    prepared = _prepare_component_layout(bound_page)
    page = prepared["page"]
    tree = prepared["tree"]
    frames = prepared["frames"]
    block_geometry = prepared["block_geometry"]
    component_geometry = prepared["component_geometry"]
    evidence = prepared["evidence"]
    initial_policy = prepared["initial_policy"]
    obligations = prepared["obligations"]
    selector_input = prepared["selector_input"]
    raw_decisions = model_layout_selector(selector_input)
    if _container_depth_exceeded(raw_decisions):
        _fail(
            "layout_decisions_too_deep",
            "authored layout decisions exceed the closed input nesting limit",
            maximum_depth=MAX_CONTAINER_DEPTH,
        )
    decisions = _validate_decisions(
        obligations,
        # Every field in selector_input is already detached from the internal
        # algorithm state. Passing it directly avoids a second full-page copy;
        # selector mutation still cannot alter the returned geometry/evidence.
        raw_decisions,
        evidence,
        initial_policy,
        tree,
    )
    policies = _propagate_dimension_policy(tree, initial_policy, decisions)
    for instance_id in component_geometry:
        component_geometry[instance_id]["dimension_policy"] = policies[instance_id]
    reference_assertions, responsive_assertions = _build_assertions(
        page,
        tree,
        component_geometry,
        policies,
        evidence,
        decisions,
    )
    result = {
        "page_key": page.get("page_key"),
        "design_state_id": page.get("design_state_id"),
        "root_instance_id": tree["root_instance_id"],
        "component_tree": tree,
        "artboard_frames_by_source_node_id": frames,
        "source_geometry_provenance_by_source_node_id": _build_source_geometry_provenance(page, frames),
        "block_geometry_by_block_id": block_geometry,
        "component_geometry_by_instance_id": component_geometry,
        "layout_evidence": evidence,
        "decision_obligations": obligations,
        "authored_layout_decisions": decisions,
        "reference_assertions": reference_assertions,
        "responsive_assertions": responsive_assertions,
        "audit_joins": _build_audit_joins(page, tree, component_geometry),
    }
    if set(result["component_geometry_by_instance_id"]) != set(tree["nodes_by_instance_id"]):
        _fail("layout_output_incomplete", "every component must have geometry and policy")
    if {value["instance_id"] for value in result["audit_joins"]} != set(tree["nodes_by_instance_id"]):
        _fail("layout_output_incomplete", "every component must have an audit join")
    return result


def verify_runtime_layout(layout_contract: JSON, runtime_probe_snapshot: JSON, viewport_kind: str) -> JSON:
    """Verify topology plus reference or responsive invariants; MAE is not used."""

    if viewport_kind not in {"reference", "responsive"}:
        _fail("runtime_viewport_kind_invalid", "viewport_kind must be reference or responsive")
    if (
        not isinstance(layout_contract, dict)
        or not isinstance(layout_contract.get("component_tree"), dict)
        or not isinstance(layout_contract["component_tree"].get("nodes_by_instance_id"), dict)
        or not isinstance(layout_contract.get("component_geometry_by_instance_id"), dict)
        or not isinstance(layout_contract.get("root_instance_id"), str)
        or not isinstance(layout_contract.get("reference_assertions"), list)
        or not isinstance(layout_contract.get("responsive_assertions"), list)
    ):
        _fail("runtime_contract_invalid", "layout contract is missing required verifier structures")
    if not isinstance(runtime_probe_snapshot, dict):
        return {"status": "fail", "failures": [{"code": "runtime_snapshot_invalid"}]}
    forbidden_self_certification = {
        "clipped",
        "operable",
        "horizontal_overflow",
        "scroll_content_end_reached",
        "renders",
        "natural_text_reflow",
        "no_clip",
        "no_overlap",
        "no_horizontal_overflow",
        "content_reachable",
        "controls_operable",
        "system_bars_correct",
        "insets_safe",
    }
    authored_flags: list[str] = []
    scan = [("$", runtime_probe_snapshot)]
    while scan:
        path, value = scan.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}"
                if key in forbidden_self_certification:
                    authored_flags.append(child_path)
                scan.append((child_path, child))
        elif isinstance(value, list):
            scan.extend((f"{path}[{index}]", child) for index, child in enumerate(value))
    expected_nodes = layout_contract["component_tree"]["nodes_by_instance_id"]
    raw_components = runtime_probe_snapshot.get("components")
    failures: list[JSON] = (
        [{"code": "runtime_self_certification_forbidden", "paths": sorted(authored_flags)}]
        if authored_flags
        else []
    )
    if not isinstance(raw_components, list):
        return {"status": "fail", "failures": [{"code": "runtime_components_missing"}]}
    by_id: dict[str, list[JSON]] = defaultdict(list)
    for component in raw_components:
        instance_id = component.get("instance_id") if isinstance(component, dict) else None
        if not isinstance(instance_id, str) or not instance_id:
            failures.append({"code": "runtime_component_invalid", "component": repr(component)})
            continue
        by_id[instance_id].append(component)
    if set(by_id) != set(expected_nodes) or any(len(values) != 1 for values in by_id.values()):
        failures.append(
            {
                "code": "runtime_component_identity_mismatch",
                "expected": sorted(expected_nodes),
                "actual": sorted(str(value) for value in by_id),
                "duplicates": sorted(str(key) for key, values in by_id.items() if len(values) != 1),
            }
        )
    measured_bounds: dict[str, JSON] = {}
    for instance_id, expected in expected_nodes.items():
        if len(by_id.get(instance_id, [])) != 1:
            continue
        actual = by_id[instance_id][0]
        expected_topology = {key: expected[key] for key in ("parent_instance_id", "slot", "order")}
        actual_topology = {key: actual.get(key) for key in ("parent_instance_id", "slot", "order")}
        if actual_topology != expected_topology:
            failures.append(
                {
                    "code": "runtime_topology_mismatch",
                    "instance_id": instance_id,
                    "expected": expected_topology,
                    "actual": actual_topology,
                }
            )
        bounds = actual.get("bounds")
        if not isinstance(bounds, dict):
            failures.append({"code": "runtime_bounds_missing", "instance_id": instance_id})
            continue
        try:
            measured_bounds[instance_id] = _validate_rect(bounds, owner=f"runtime:{instance_id}")
        except LayoutContractError as error:
            failures.append({"code": "runtime_bounds_invalid", "instance_id": instance_id, "message": str(error)})
            continue
        if viewport_kind == "responsive":
            if bounds["width"] <= 0 or bounds["height"] <= 0:
                failures.append({"code": "runtime_component_has_no_area", "instance_id": instance_id})
            continue
        expected_bounds = layout_contract["component_geometry_by_instance_id"][instance_id]["artboard_envelope"]
        if expected_bounds is None:
            continue
        policy = layout_contract["component_geometry_by_instance_id"][instance_id]["dimension_policy"]
        if instance_id == layout_contract["root_instance_id"]:
            fields = ("left", "top", "width", "height")
        else:
            fields = []
            if policy["x"]["reference"] != "flow_relative":
                fields.append("left")
            if policy["y"]["reference"] != "flow_relative":
                fields.append("top")
            if policy["width"]["reference"] == "exact":
                fields.append("width")
            if policy["height"]["reference"] == "exact":
                fields.append("height")
        mismatches = {
            field: {"expected": expected_bounds[field], "actual": bounds.get(field)}
            for field in fields
            if bounds.get(field) != expected_bounds[field]
        }
        if mismatches:
            failures.append({"code": "runtime_reference_geometry_mismatch", "instance_id": instance_id, "fields": mismatches})

    if viewport_kind == "reference":
        for assertion in layout_contract.get("reference_assertions", []):
            if assertion.get("kind") != "sibling_gap":
                continue
            previous = measured_bounds.get(assertion["previous_instance_id"])
            current = measured_bounds.get(assertion["current_instance_id"])
            if previous is None or current is None:
                continue
            if assertion["axis"] == "vertical":
                actual_gap = current["top"] - _bottom(previous)
            else:
                actual_gap = current["left"] - _right(previous)
            if actual_gap != assertion["expected_gap"]:
                failures.append(
                    {
                        "code": "runtime_sibling_gap_mismatch",
                        "evidence_id": assertion["evidence_id"],
                        "previous_instance_id": assertion["previous_instance_id"],
                        "current_instance_id": assertion["current_instance_id"],
                        "axis": assertion["axis"],
                        "expected_gap": assertion["expected_gap"],
                        "actual_gap": actual_gap,
                    }
                )
    else:
        coordinate_space = runtime_probe_snapshot.get("coordinate_space")
        if coordinate_space != {"unit": "dp", "origin": "viewport"}:
            failures.append({"code": "runtime_coordinate_space_invalid"})
        safe_insets = runtime_probe_snapshot.get("safe_insets")
        if (
            not isinstance(safe_insets, dict)
            or set(safe_insets) != {"left", "top", "right", "bottom"}
            or any(
                not _finite_number(value) or value < 0
                for value in safe_insets.values()
            )
        ):
            failures.append({"code": "runtime_safe_insets_invalid"})
            safe_insets = None
        system_bars = runtime_probe_snapshot.get("system_bars")
        bars_valid = isinstance(system_bars, dict) and set(system_bars) == {
            "status",
            "navigation",
        }
        if bars_valid:
            for name in ("status", "navigation"):
                bar = system_bars[name]
                if (
                    not isinstance(bar, dict)
                    or set(bar) != {"visible", "bounds"}
                    or type(bar.get("visible")) is not bool
                    or (bar["visible"] and not isinstance(bar.get("bounds"), dict))
                    or (not bar["visible"] and bar.get("bounds") is not None)
                ):
                    bars_valid = False
                    break
                if bar["visible"]:
                    try:
                        _validate_rect(bar["bounds"], owner=f"runtime:system-bar:{name}")
                    except LayoutContractError:
                        bars_valid = False
                        break
        if not bars_valid:
            failures.append({"code": "runtime_system_bars_invalid"})
        viewport = runtime_probe_snapshot.get("viewport_bounds")
        if not isinstance(viewport, dict):
            failures.append({"code": "runtime_viewport_bounds_missing"})
            viewport_rect = None
        else:
            try:
                viewport_rect = _validate_rect(viewport, owner="runtime:viewport")
            except LayoutContractError as error:
                failures.append({"code": "runtime_viewport_bounds_invalid", "message": str(error)})
                viewport_rect = None

        for assertion in layout_contract.get("responsive_assertions", []):
            if assertion.get("kind") == "no_unintended_overlap_group":
                member_ids = [
                    instance_id
                    for instance_id in assertion["member_instance_ids"]
                    if instance_id in measured_bounds
                ]
                allowed = {
                    frozenset(pair)
                    for pair in assertion["allowed_overlap_pairs"]
                }
                runtime_geometry = {
                    instance_id: {"artboard_envelope": measured_bounds[instance_id]}
                    for instance_id in member_ids
                }
                for first_id, second_id in _overlapping_pairs(member_ids, runtime_geometry):
                    if frozenset((first_id, second_id)) in allowed:
                        continue
                    failures.append(
                        {
                            "code": "runtime_unintended_overlap",
                            "parent_instance_id": assertion["parent_instance_id"],
                            "first_instance_id": first_id,
                            "second_instance_id": second_id,
                            "overlap": _intersection(measured_bounds[first_id], measured_bounds[second_id]),
                        }
                    )
            elif assertion.get("kind") == "scroll_reachability":
                observations = runtime_probe_snapshot.get("driver_observations")
                results = (
                    observations.get("scroll_results")
                    if isinstance(observations, dict)
                    else None
                )
                matches = [
                    item
                    for item in results or []
                    if isinstance(item, dict)
                    and item.get("decision_id") == assertion["decision_id"]
                ]
                container_id = assertion["container_instance_id"]
                required_ids: set[str] = set()
                for instance_id in expected_nodes:
                    current_id: str | None = instance_id
                    while current_id is not None:
                        if current_id == container_id:
                            required_ids.add(instance_id)
                            break
                        current = expected_nodes.get(current_id)
                        current_id = (
                            current.get("parent_instance_id")
                            if isinstance(current, dict)
                            else None
                        )
                valid_result = False
                if len(matches) == 1:
                    result = matches[0]
                    observed_ids = result.get("observed_instance_ids")
                    valid_result = (
                        set(result)
                        == {
                            "decision_id",
                            "container_instance_id",
                            "axis",
                            "end_reached",
                            "restored_to_start",
                            "observed_instance_ids",
                        }
                        and result.get("container_instance_id") == container_id
                        and result.get("axis") == assertion["axis"]
                        and result.get("end_reached") is True
                        and result.get("restored_to_start") is True
                        and isinstance(observed_ids, list)
                        and all(isinstance(value, str) and value for value in observed_ids)
                        and len(observed_ids) == len(set(observed_ids))
                        and required_ids.issubset(set(observed_ids))
                    )
                if not valid_result:
                    failures.append(
                        {
                            "code": "runtime_scroll_unreachable",
                            "decision_id": assertion["decision_id"],
                        }
                    )

        if viewport_rect is not None:
            if safe_insets is not None:
                viewport_rect = {
                    "left": viewport_rect["left"] + safe_insets["left"],
                    "top": viewport_rect["top"] + safe_insets["top"],
                    "width": max(
                        0,
                        viewport_rect["width"]
                        - safe_insets["left"]
                        - safe_insets["right"],
                    ),
                    "height": max(
                        0,
                        viewport_rect["height"]
                        - safe_insets["top"]
                        - safe_insets["bottom"],
                    ),
                }
            overflow_allowances = {
                assertion["instance_id"]: assertion
                for assertion in layout_contract.get("responsive_assertions", [])
                if assertion.get("kind") == "horizontal_overflow_allowance"
            }
            horizontal_scroll_members = {
                instance_id
                for assertion in layout_contract.get("responsive_assertions", [])
                if assertion.get("kind") == "horizontal_overflow_scope"
                for instance_id in assertion.get("allowed_instance_ids", [])
            }
            vertical_scroll_members = {
                instance_id
                for assertion in layout_contract.get("responsive_assertions", [])
                if assertion.get("kind") == "scroll_overflow_scope"
                and assertion.get("axis") == "vertical"
                for instance_id in assertion.get("allowed_instance_ids", [])
            }
            for instance_id in sorted(set(overflow_allowances) - horizontal_scroll_members):
                bounds = measured_bounds.get(instance_id)
                if bounds is None:
                    continue
                allowance = overflow_allowances[instance_id]
                if (
                    bounds["left"] < viewport_rect["left"] - allowance["left"]
                    or _right(bounds) > _right(viewport_rect) + allowance["right"]
                ):
                    failures.append(
                        {
                            "code": "runtime_horizontal_overflow",
                            "instance_id": instance_id,
                            "viewport_bounds": viewport_rect,
                            "component_bounds": bounds,
                            "reference_allowance": {"left": allowance["left"], "right": allowance["right"]},
                        }
                    )
            vertical_allowances = {
                assertion["instance_id"]: assertion
                for assertion in layout_contract.get("responsive_assertions", [])
                if assertion.get("kind") == "vertical_clipping_allowance"
            }
            for instance_id in sorted(
                set(vertical_allowances) - vertical_scroll_members
            ):
                bounds = measured_bounds.get(instance_id)
                if bounds is None:
                    continue
                allowance = vertical_allowances[instance_id]
                if (
                    bounds["top"] < viewport_rect["top"] - allowance["top"]
                    or _bottom(bounds)
                    > _bottom(viewport_rect) + allowance["bottom"]
                ):
                    failures.append(
                        {
                            "code": "runtime_vertical_clipping",
                            "instance_id": instance_id,
                            "viewport_bounds": viewport_rect,
                            "component_bounds": bounds,
                            "reference_allowance": {
                                "top": allowance["top"],
                                "bottom": allowance["bottom"],
                            },
                        }
                    )
    return {"status": "pass" if not failures else "fail", "failures": failures}


__all__ = [
    "LayoutContractError",
    "derive_component_layout",
    "prepare_component_layout_selection",
    "verify_runtime_layout",
]
