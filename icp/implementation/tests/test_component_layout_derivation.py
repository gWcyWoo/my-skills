import copy
import unittest
from unittest.mock import patch

from icp.implementation.scripts import component_layout_derivation as layout_module
from icp.implementation.scripts.component_layout_derivation import (
    LayoutContractError,
    derive_component_layout,
    verify_runtime_layout,
)


def rect(left, top, width, height):
    return {"left": left, "top": top, "width": width, "height": height}


def bound_page():
    return {
        "page_key": "permission",
        "design_state_id": "permission-ru",
        "root_instance_id": "page",
        "reference": {
            "root_source_node_id": "root-node",
            "logical_artboard_size": {"width": 390, "height": 886},
            "coordinate_contract": {
                "supported_frame_spaces": ["canvas", "artboard", "parent"]
            },
        },
        # Deliberately shuffled: storage order has no layout meaning.
        "instances": [
            {
                "instance_id": "footer",
                "component_id": "footer-component",
                "parent_instance_id": "page",
                "slot": "footer",
                "order": 0,
                "source_block_ids": ["footer-block"],
            },
            {
                "instance_id": "card-b",
                "component_id": "card-component",
                "parent_instance_id": "content",
                "slot": "items",
                "order": 1,
                "source_block_ids": ["card-b-block"],
            },
            {
                "instance_id": "page",
                "component_id": "page-component",
                "parent_instance_id": None,
                "slot": "root",
                "order": 0,
                "source_block_ids": ["page-block"],
            },
            {
                "instance_id": "content",
                "component_id": "content-component",
                "parent_instance_id": "page",
                "slot": "body",
                "order": 0,
                "source_block_ids": ["content-block"],
            },
            {
                "instance_id": "card-a",
                "component_id": "card-component",
                "parent_instance_id": "content",
                "slot": "items",
                "order": 0,
                "source_block_ids": ["card-a-block", "card-a-decoration-block"],
            },
        ],
        "blocks_by_id": {
            "page-block": {
                "block_id": "page-block",
                "semantic_parent_block_id": None,
                "ordered_source_node_ids": ["root-node"],
                "rendering_source_node_ids": ["root-node"],
                "non_rendering_source_node_ids": [],
                "content_roles_by_source_node_id": {"root-node": "static_visual"},
            },
            "content-block": {
                "block_id": "content-block",
                "semantic_parent_block_id": "page-block",
                "ordered_source_node_ids": ["content-node"],
                "rendering_source_node_ids": ["content-node"],
                "non_rendering_source_node_ids": [],
                "content_roles_by_source_node_id": {"content-node": "static_visual"},
            },
            "card-a-block": {
                "block_id": "card-a-block",
                "semantic_parent_block_id": "content-block",
                "ordered_source_node_ids": ["card-a-node", "card-a-text"],
                "rendering_source_node_ids": ["card-a-node", "card-a-text"],
                "non_rendering_source_node_ids": [],
                "content_roles_by_source_node_id": {
                    "card-a-node": "static_visual",
                    "card-a-text": "static_copy",
                },
            },
            "card-a-decoration-block": {
                "block_id": "card-a-decoration-block",
                "semantic_parent_block_id": "content-block",
                "ordered_source_node_ids": ["decoration-node"],
                "rendering_source_node_ids": ["decoration-node"],
                "non_rendering_source_node_ids": [],
                "content_roles_by_source_node_id": {
                    "decoration-node": "static_visual"
                },
            },
            "card-b-block": {
                "block_id": "card-b-block",
                "semantic_parent_block_id": "content-block",
                "ordered_source_node_ids": ["card-b-node", "card-b-icon"],
                "rendering_source_node_ids": ["card-b-node", "card-b-icon"],
                "non_rendering_source_node_ids": [],
                "content_roles_by_source_node_id": {
                    "card-b-node": "static_visual",
                    "card-b-icon": "platform_element",
                },
            },
            "footer-block": {
                "block_id": "footer-block",
                "semantic_parent_block_id": "page-block",
                "ordered_source_node_ids": ["footer-node"],
                "rendering_source_node_ids": ["footer-node"],
                "non_rendering_source_node_ids": [],
                "content_roles_by_source_node_id": {"footer-node": "static_copy"},
            },
        },
        "source_nodes_by_id": {
            "root-node": {
                "source_node_id": "root-node",
                "source_parent_node_id": None,
                "source_order": 0,
                "frame": rect(687, 2050, 390, 886),
                "real_frame": None,
                "geometry_basis": "frame",
                "frame_space": "canvas",
            },
            "content-node": {
                "source_node_id": "content-node",
                "source_parent_node_id": "root-node",
                "source_order": 1,
                "frame": rect(16, 104, 358, 620),
                "real_frame": None,
                "geometry_basis": "frame",
                "frame_space": "artboard",
            },
            "card-a-node": {
                "source_node_id": "card-a-node",
                "source_parent_node_id": "content-node",
                "source_order": 2,
                "frame": rect(16, 104, 358, 182),
                "real_frame": None,
                "geometry_basis": "frame",
                "frame_space": "artboard",
            },
            "card-a-text": {
                "source_node_id": "card-a-text",
                "source_parent_node_id": "card-a-node",
                "source_order": 3,
                "frame": rect(32, 132, 260, 66),
                "real_frame": None,
                "geometry_basis": "frame",
                "frame_space": "artboard",
            },
            "decoration-node": {
                "source_node_id": "decoration-node",
                "source_parent_node_id": "content-node",
                "source_order": 4,
                "frame": rect(-4, 96, 20, 20),
                "real_frame": None,
                "geometry_basis": "frame",
                "frame_space": "artboard",
            },
            "card-b-node": {
                "source_node_id": "card-b-node",
                "source_parent_node_id": "content-node",
                "source_order": 5,
                "frame": rect(16, 302, 358, 182),
                "real_frame": None,
                "geometry_basis": "frame",
                "frame_space": "artboard",
            },
            "card-b-icon": {
                "source_node_id": "card-b-icon",
                "source_parent_node_id": "card-b-node",
                "source_order": 6,
                "frame": rect(40, 330, 56, 56),
                "real_frame": rect(42, 332, 52, 52),
                "geometry_basis": "real_frame",
                "frame_space": "artboard",
            },
            "footer-node": {
                "source_node_id": "footer-node",
                "source_parent_node_id": "root-node",
                "source_order": 7,
                "frame": rect(16, 760, 358, 90),
                "real_frame": None,
                "geometry_basis": "frame",
                "frame_space": "artboard",
            },
        },
        "component_definitions_by_id": {
            "page-component": {
                "component_id": "page-component",
                "kind": "page",
                "slots": [
                    {"slot_id": "body", "role": "content", "cardinality": "one"},
                    {"slot_id": "footer", "role": "action", "cardinality": "one"},
                ],
            },
            "content-component": {
                "component_id": "content-component",
                "kind": "container",
                "slots": [
                    {"slot_id": "items", "role": "content", "cardinality": "many"}
                ],
            },
            "card-component": {
                "component_id": "card-component",
                "kind": "content",
                "slots": [],
            },
            "footer-component": {
                "component_id": "footer-component",
                "kind": "action",
                "slots": [],
            },
        },
        "platform_context": {
            "platform": "android",
            "project_common_rules": ["content driven sizing"],
            "platform_best_practices": ["scroll long content"],
        },
    }


def selector(selector_input):
    decisions = []
    for obligation in selector_input["decision_obligations"]:
        scope = obligation["scope"]
        member_ids = obligation["member_ids"]
        if scope == "slot" and obligation["slot"] == "items":
            layout_kind = "flow"
            main_axis = "vertical"
        elif scope == "slots":
            layout_kind = "flow"
            main_axis = "vertical"
        else:
            layout_kind = "flow"
            main_axis = "none"
        decisions.append(
            {
                "decision_id": obligation["decision_id"],
                "scope": scope,
                "parent_instance_id": obligation["parent_instance_id"],
                "slot": obligation["slot"],
                "ordered_member_ids": member_ids,
                "layout_kind": layout_kind,
                "main_axis": main_axis,
                "sizing_policy": {"width": "constraint", "height": "content"},
                "alignment_policy": "source_evidence",
                "constraints": [],
                "overflow_policy": "reachable",
                "evidence_ids": obligation["evidence_ids"],
                "rationale": "Use content-driven flow from the frozen topology and evidence.",
            }
        )
    return decisions


def runtime_components(contract):
    result = []
    for instance_id, node in contract["component_tree"]["nodes_by_instance_id"].items():
        geometry = contract["component_geometry_by_instance_id"][instance_id]
        result.append(
            {
                "instance_id": instance_id,
                "parent_instance_id": node["parent_instance_id"],
                "slot": node["slot"],
                "order": node["order"],
                "bounds": copy.deepcopy(geometry["artboard_envelope"]),
            }
        )
    return result


def responsive_snapshot(components, **changes):
    value = {
        "coordinate_space": {"unit": "dp", "origin": "viewport"},
        "viewport_bounds": rect(0, 0, 390, 640),
        "safe_insets": {"left": 0, "top": 0, "right": 0, "bottom": 0},
        "system_bars": {
            "status": {"visible": False, "bounds": None},
            "navigation": {"visible": False, "bounds": None},
        },
        "scroll_metrics": [],
        "components": components,
    }
    value.update(changes)
    return value


class ComponentLayoutDerivationTest(unittest.TestCase):
    def test_derives_component_local_geometry_without_using_storage_order(self):
        page = bound_page()
        result = derive_component_layout(page, selector)

        self.assertEqual(
            result["artboard_frames_by_source_node_id"]["root-node"],
            rect(0, 0, 390, 886),
        )
        self.assertEqual(
            result["artboard_frames_by_source_node_id"]["content-node"],
            rect(16, 104, 358, 620),
        )
        self.assertEqual(
            result["artboard_frames_by_source_node_id"]["card-b-icon"],
            rect(42, 332, 52, 52),
        )
        self.assertEqual(
            result["source_geometry_provenance_by_source_node_id"]["card-b-icon"],
            {
                "source_node_id": "card-b-icon",
                "source_parent_node_id": "card-b-node",
                "source_order": 6,
                "geometry_basis": "real_frame",
                "frame_space": "artboard",
                "frame": rect(40, 330, 56, 56),
                "real_frame": rect(42, 332, 52, 52),
                "resolved_artboard_frame": rect(42, 332, 52, 52),
            },
        )
        self.assertEqual(
            result["component_tree"]["children_by_parent_and_slot"]["content"]["items"],
            ["card-a", "card-b"],
        )
        self.assertEqual(
            result["component_geometry_by_instance_id"]["card-a"]["boundary_regions"],
            [
                {"block_id": "card-a-block", "source_node_id": "card-a-node", "rect": rect(16, 104, 358, 182)},
                {"block_id": "card-a-decoration-block", "source_node_id": "decoration-node", "rect": rect(-4, 96, 20, 20)},
            ],
        )
        self.assertEqual(
            result["component_geometry_by_instance_id"]["card-b"]["local_envelope"],
            rect(0, 198, 358, 182),
        )

    def test_derives_same_slot_cross_slot_and_source_paint_evidence(self):
        result = derive_component_layout(bound_page(), selector)
        evidence = result["layout_evidence"]
        kinds = {item["kind"] for item in evidence}

        self.assertIn("sibling_relation", kinds)
        self.assertIn("cross_slot_relation", kinds)
        self.assertNotIn("source_paint_order", kinds)
        sibling = next(item for item in evidence if item["kind"] == "sibling_relation")
        self.assertEqual(sibling["previous_instance_id"], "card-a")
        self.assertEqual(sibling["current_instance_id"], "card-b")
        self.assertEqual(sibling["vertical_gap"], 16)

    def test_propagates_adaptive_position_only_after_axis_is_selected(self):
        result = derive_component_layout(bound_page(), selector)
        policies = result["component_geometry_by_instance_id"]

        self.assertEqual(policies["card-a"]["dimension_policy"]["height"]["runtime"], "content_driven")
        self.assertEqual(policies["card-b"]["dimension_policy"]["y"]["runtime"], "flow_relative")
        self.assertEqual(policies["card-b"]["dimension_policy"]["x"]["runtime"], "reference_relation")
        self.assertEqual(policies["content"]["dimension_policy"]["height"]["runtime"], "content_driven")

    def test_canvas_and_parent_frames_convert_exactly_once(self):
        page = bound_page()
        page["source_nodes_by_id"]["canvas-child"] = {
            "source_node_id": "canvas-child",
            "source_parent_node_id": "root-node",
            "source_order": 8,
            "frame": rect(700, 2060, 10, 10),
            "real_frame": None,
            "geometry_basis": "frame",
            "frame_space": "canvas",
        }
        page["source_nodes_by_id"]["parent-child"] = {
            "source_node_id": "parent-child",
            "source_parent_node_id": "content-node",
            "source_order": 9,
            "frame": rect(3, 4, 5, 6),
            "real_frame": None,
            "geometry_basis": "frame",
            "frame_space": "parent",
        }
        page["blocks_by_id"]["content-block"]["ordered_source_node_ids"] += [
            "canvas-child",
            "parent-child",
        ]
        page["blocks_by_id"]["content-block"]["non_rendering_source_node_ids"] += [
            "canvas-child",
            "parent-child",
        ]
        page["blocks_by_id"]["content-block"]["content_roles_by_source_node_id"].update(
            {"canvas-child": "static_visual", "parent-child": "static_visual"}
        )

        result = derive_component_layout(page, selector)
        self.assertEqual(result["artboard_frames_by_source_node_id"]["canvas-child"], rect(13, 10, 10, 10))
        self.assertEqual(result["artboard_frames_by_source_node_id"]["parent-child"], rect(19, 108, 5, 6))

    def test_rejects_duplicate_or_non_contiguous_explicit_order(self):
        page = bound_page()
        page["instances"][1]["order"] = 0
        with self.assertRaisesRegex(LayoutContractError, "sibling_order_invalid"):
            derive_component_layout(page, selector)

        page = bound_page()
        page["instances"][1]["order"] = 3
        with self.assertRaisesRegex(LayoutContractError, "sibling_order_invalid"):
            derive_component_layout(page, selector)

    def test_rejects_missing_coordinate_semantics_and_block_ownership(self):
        page = bound_page()
        del page["source_nodes_by_id"]["card-a-node"]["frame_space"]
        with self.assertRaisesRegex(LayoutContractError, "source_frame_space_invalid"):
            derive_component_layout(page, selector)

        page = bound_page()
        page["instances"][1]["source_block_ids"].append("card-a-block")
        with self.assertRaisesRegex(LayoutContractError, "block_ownership_invalid"):
            derive_component_layout(page, selector)

    def test_rejects_decision_that_changes_order_or_uses_unsupported_fixed_height(self):
        def bad_order_selector(selector_input):
            decisions = selector(selector_input)
            item = next(value for value in decisions if value["slot"] == "items")
            item["ordered_member_ids"] = list(reversed(item["ordered_member_ids"]))
            return decisions

        with self.assertRaisesRegex(LayoutContractError, "decision_members_invalid"):
            derive_component_layout(bound_page(), bad_order_selector)

        def fixed_text_selector(selector_input):
            decisions = selector(selector_input)
            item = next(value for value in decisions if value["slot"] == "items")
            item["sizing_policy"]["height"] = "fixed"
            return decisions

        with self.assertRaisesRegex(LayoutContractError, "fixed_adaptive_dimension"):
            derive_component_layout(bound_page(), fixed_text_selector)

    def test_exact_numeric_constraint_requires_a_closed_evidence_expression(self):
        def numeric_selector(selector_input):
            decisions = selector(selector_input)
            item = next(value for value in decisions if value["slot"] == "items")
            evidence = next(
                value
                for value in selector_input["layout_evidence"]
                if value["kind"] == "sibling_relation"
            )
            item["constraints"] = [
                {
                    "target": {
                        "kind": "gap",
                        "axis": "vertical",
                        "previous_instance_id": "card-a",
                        "current_instance_id": "card-b",
                    },
                    "expression": {
                        "op": "copy",
                        "evidence_id": evidence["evidence_id"],
                        "field": "vertical_gap",
                    },
                }
            ]
            return decisions

        result = derive_component_layout(bound_page(), numeric_selector)
        decision = next(item for item in result["authored_layout_decisions"] if item["slot"] == "items")
        self.assertEqual(decision["constraints"][0]["resolved_value"], 16)

        def raw_numeric_selector(selector_input):
            decisions = selector(selector_input)
            item = next(value for value in decisions if value["slot"] == "items")
            item["constraints"] = [
                {
                    "target": {
                        "kind": "gap",
                        "axis": "vertical",
                        "previous_instance_id": "card-a",
                        "current_instance_id": "card-b",
                    },
                    "value": 16,
                }
            ]
            return decisions

        with self.assertRaisesRegex(LayoutContractError, "constraint_schema_invalid"):
            derive_component_layout(bound_page(), raw_numeric_selector)

    def test_runtime_reference_and_responsive_checks_use_topology_not_mae(self):
        result = derive_component_layout(bound_page(), selector)
        components = []
        for instance_id, node in result["component_tree"]["nodes_by_instance_id"].items():
            geometry = result["component_geometry_by_instance_id"][instance_id]
            components.append(
                {
                    "instance_id": instance_id,
                    "parent_instance_id": node["parent_instance_id"],
                    "slot": node["slot"],
                    "order": node["order"],
                    "bounds": geometry["artboard_envelope"],
                }
            )
        reference = verify_runtime_layout(result, {"components": components}, "reference")
        self.assertEqual(reference, {"status": "pass", "failures": []})

        responsive_components = copy.deepcopy(components)
        for item in responsive_components:
            if item["instance_id"] == "card-a":
                item["bounds"]["height"] += 44
            if item["instance_id"] == "card-b":
                item["bounds"]["top"] += 44
        responsive = verify_runtime_layout(
            result,
            responsive_snapshot(
                responsive_components,
                viewport_bounds=rect(0, 0, 390, 900),
            ),
            "responsive",
        )
        self.assertEqual(responsive, {"status": "pass", "failures": []})

        responsive_components[0]["slot"] = "wrong"
        failed = verify_runtime_layout(
            result,
            responsive_snapshot(
                responsive_components,
                viewport_bounds=rect(0, 0, 390, 900),
            ),
            "responsive",
        )
        self.assertEqual(failed["status"], "fail")
        self.assertIn("runtime_topology_mismatch", {item["code"] for item in failed["failures"]})

    def test_horizontal_flow_propagates_x_without_inventing_vertical_flow(self):
        def horizontal_selector(selector_input):
            decisions = selector(selector_input)
            item = next(value for value in decisions if value["slot"] == "items")
            item["main_axis"] = "horizontal"
            return decisions

        result = derive_component_layout(bound_page(), horizontal_selector)
        policies = result["component_geometry_by_instance_id"]
        self.assertEqual(policies["card-b"]["dimension_policy"]["x"]["runtime"], "flow_relative")
        self.assertEqual(policies["card-b"]["dimension_policy"]["y"]["runtime"], "reference_relation")

    def test_combined_geometry_unions_both_recorded_frames(self):
        page = bound_page()
        icon = page["source_nodes_by_id"]["card-b-icon"]
        icon["geometry_basis"] = "combined"
        result = derive_component_layout(page, selector)
        self.assertEqual(
            result["artboard_frames_by_source_node_id"]["card-b-icon"],
            rect(40, 330, 56, 56),
        )

    def test_required_slot_and_stage_boundary_fail_closed(self):
        page = bound_page()
        page["instances"] = [value for value in page["instances"] if value["instance_id"] != "footer"]
        del page["blocks_by_id"]["footer-block"]
        with self.assertRaisesRegex(LayoutContractError, "component_slot_invalid"):
            derive_component_layout(page, selector)

        page = bound_page()
        page["ui_description"] = "must not be read here"
        with self.assertRaisesRegex(LayoutContractError, "stage_boundary_violation"):
            derive_component_layout(page, selector)

    def test_constraint_cannot_cite_evidence_outside_its_obligation(self):
        def unrelated_evidence_selector(selector_input):
            decisions = selector(selector_input)
            item = next(value for value in decisions if value["slot"] == "items")
            unrelated = next(
                value
                for value in selector_input["layout_evidence"]
                if value["kind"] == "cross_slot_relation"
            )
            item["evidence_ids"] = [unrelated["evidence_id"]]
            item["constraints"] = [
                {
                    "target": "vertical_gap",
                    "expression": {
                        "op": "copy",
                        "evidence_id": unrelated["evidence_id"],
                        "field": "vertical_gap",
                    },
                }
            ]
            return decisions

        with self.assertRaisesRegex(LayoutContractError, "constraint_evidence_invalid"):
            derive_component_layout(bound_page(), unrelated_evidence_selector)

    def test_derivation_is_deterministic_and_does_not_mutate_input(self):
        page = bound_page()
        original = copy.deepcopy(page)
        first = derive_component_layout(page, selector)
        second = derive_component_layout(page, selector)
        self.assertEqual(first, second)
        self.assertEqual(page, original)

        float_page = copy.deepcopy(page)
        for node in float_page["source_nodes_by_id"].values():
            for field in ("frame", "real_frame"):
                if node.get(field):
                    node[field] = {key: float(value) for key, value in node[field].items()}
        float_result = derive_component_layout(float_page, selector)
        self.assertEqual(
            [item["evidence_id"] for item in first["layout_evidence"]],
            [item["evidence_id"] for item in float_result["layout_evidence"]],
        )

    def test_selector_input_is_detached_without_a_second_full_page_copy(self):
        def mutating_selector(selector_input):
            decisions = selector(selector_input)
            selector_input["component_geometry_by_instance_id"]["card-a"]["artboard_envelope"]["left"] = 999
            selector_input["layout_evidence"].clear()
            return decisions

        result = derive_component_layout(bound_page(), mutating_selector)
        self.assertEqual(result["component_geometry_by_instance_id"]["card-a"]["artboard_envelope"]["left"], -4)
        self.assertTrue(result["layout_evidence"])

    def test_runtime_verifier_collects_all_observed_failures(self):
        result = derive_component_layout(bound_page(), selector)
        components = runtime_components(result)
        card_a = next(item for item in components if item["instance_id"] == "card-a")
        card_b = next(item for item in components if item["instance_id"] == "card-b")
        card_b["bounds"]["left"] = card_a["bounds"]["left"]
        card_b["bounds"]["top"] = card_a["bounds"]["top"]
        card_b["bounds"]["width"] = 500
        footer = next(item for item in components if item["instance_id"] == "footer")
        footer["slot"] = "wrong"
        checked = verify_runtime_layout(
            result,
            responsive_snapshot(components),
            "responsive",
        )
        self.assertEqual(checked["status"], "fail")
        self.assertTrue(
            {
                "runtime_topology_mismatch",
                "runtime_unintended_overlap",
                "runtime_horizontal_overflow",
            }.issubset({item["code"] for item in checked["failures"]})
        )

    def test_reference_verification_preserves_sourced_gap_after_natural_height_change(self):
        result = derive_component_layout(bound_page(), selector)
        components = runtime_components(result)
        card_a = next(item for item in components if item["instance_id"] == "card-a")
        card_b = next(item for item in components if item["instance_id"] == "card-b")
        card_a["bounds"]["height"] += 44
        card_b["bounds"]["top"] += 52

        checked = verify_runtime_layout(result, {"components": components}, "reference")
        self.assertEqual(checked["status"], "fail")
        failure = next(item for item in checked["failures"] if item["code"] == "runtime_sibling_gap_mismatch")
        self.assertEqual(failure["expected_gap"], 16)
        self.assertEqual(failure["actual_gap"], 24)

    def test_responsive_geometry_detects_overlap_and_horizontal_overflow_from_bounds(self):
        result = derive_component_layout(bound_page(), selector)
        components = runtime_components(result)
        card_a = next(item for item in components if item["instance_id"] == "card-a")
        card_b = next(item for item in components if item["instance_id"] == "card-b")
        card_b["bounds"]["top"] = card_a["bounds"]["top"]
        card_b["bounds"]["left"] = card_a["bounds"]["left"]
        card_b["bounds"]["width"] = 500

        checked = verify_runtime_layout(
            result,
            responsive_snapshot(components),
            "responsive",
        )
        codes = {item["code"] for item in checked["failures"]}
        self.assertIn("runtime_unintended_overlap", codes)
        self.assertIn("runtime_horizontal_overflow", codes)

    def test_adaptive_content_cannot_be_declared_intrinsic_or_fixed_by_selector(self):
        for forbidden in ("intrinsic", "fixed"):
            with self.subTest(forbidden=forbidden):
                def bad_selector(selector_input, sizing=forbidden):
                    decisions = selector(selector_input)
                    item = next(value for value in decisions if value["slot"] == "items")
                    item["sizing_policy"]["height"] = sizing
                    return decisions

                with self.assertRaisesRegex(LayoutContractError, "fixed_adaptive_dimension"):
                    derive_component_layout(bound_page(), bad_selector)

    def test_flow_relative_member_cannot_receive_an_absolute_position_constraint(self):
        def absolute_selector(selector_input):
            decisions = selector(selector_input)
            item = next(value for value in decisions if value["slot"] == "items")
            evidence = next(
                value
                for value in selector_input["layout_evidence"]
                if value["kind"] == "parent_child" and value["child_instance_id"] == "card-b"
            )
            item["evidence_ids"] = list(dict.fromkeys(item["evidence_ids"] + [evidence["evidence_id"]]))
            item["constraints"] = [
                {
                    "target": {
                        "kind": "position",
                        "instance_id": "card-b",
                        "axis": "y",
                    },
                    "expression": {
                        "op": "copy",
                        "evidence_id": evidence["evidence_id"],
                        "field": "top_inset",
                    },
                }
            ]
            return decisions

        with self.assertRaisesRegex(LayoutContractError, "constraint_position_invalid"):
            derive_component_layout(bound_page(), absolute_selector)

    def test_non_visual_wrapper_derives_its_geometry_from_visual_children(self):
        page = bound_page()
        content = next(value for value in page["instances"] if value["instance_id"] == "content")
        content["parent_instance_id"] = "scroll-wrapper"
        content["slot"] = "items"
        page["instances"].append(
            {
                "instance_id": "scroll-wrapper",
                "component_id": "content-component",
                "parent_instance_id": "page",
                "slot": "body",
                "order": 0,
                "source_block_ids": [],
            }
        )
        result = derive_component_layout(page, selector)
        wrapper = result["component_geometry_by_instance_id"]["scroll-wrapper"]
        self.assertEqual(wrapper["geometry_source"], "descendant_union")
        self.assertEqual(wrapper["artboard_envelope"], rect(16, 104, 358, 620))
        self.assertEqual(
            result["component_geometry_by_instance_id"]["content"]["local_envelope"],
            rect(0, 0, 358, 620),
        )

    def test_geometry_relevant_source_contract_fails_closed(self):
        page = bound_page()
        page["blocks_by_id"]["card-a-block"]["content_roles_by_source_node_id"]["card-a-text"] = "copy"
        with self.assertRaisesRegex(LayoutContractError, "content_role_invalid"):
            derive_component_layout(page, selector)

        page = bound_page()
        page["blocks_by_id"]["card-a-block"]["semantic_parent_block_id"] = "missing-block"
        with self.assertRaisesRegex(LayoutContractError, "semantic_parent_block_invalid"):
            derive_component_layout(page, selector)

        page = bound_page()
        page["blocks_by_id"]["card-b-block"]["ordered_source_node_ids"].append("card-a-text")
        page["blocks_by_id"]["card-b-block"]["rendering_source_node_ids"].append("card-a-text")
        page["blocks_by_id"]["card-b-block"]["content_roles_by_source_node_id"]["card-a-text"] = "static_copy"
        with self.assertRaisesRegex(LayoutContractError, "source_node_block_ownership_invalid"):
            derive_component_layout(page, selector)

    def test_root_topology_and_semantic_block_tree_are_validated_before_derivation(self):
        page = bound_page()
        root = next(value for value in page["instances"] if value["instance_id"] == "page")
        del root["slot"]
        with self.assertRaisesRegex(LayoutContractError, "component_tree_invalid"):
            derive_component_layout(page, selector)

        page = bound_page()
        page["blocks_by_id"]["page-block"]["semantic_parent_block_id"] = "content-block"
        with self.assertRaisesRegex(LayoutContractError, "semantic_parent_block_invalid"):
            derive_component_layout(page, selector)

    def test_every_projected_source_node_must_belong_to_one_block(self):
        page = bound_page()
        page["source_nodes_by_id"]["orphan-node"] = {
            "source_node_id": "orphan-node",
            "source_parent_node_id": "root-node",
            "source_order": 8,
            "frame": rect(8, 8, 8, 8),
            "real_frame": None,
            "geometry_basis": "frame",
            "frame_space": "artboard",
        }
        with self.assertRaisesRegex(LayoutContractError, "source_node_block_ownership_invalid"):
            derive_component_layout(page, selector)

    def test_alignment_policy_and_overlay_choice_use_closed_evidence(self):
        def bad_alignment(selector_input):
            decisions = selector(selector_input)
            decisions[0]["alignment_policy"] = {"unreviewed": True}
            return decisions

        with self.assertRaisesRegex(LayoutContractError, "layout_decision_schema_invalid"):
            derive_component_layout(bound_page(), bad_alignment)

        def unsupported_overlay(selector_input):
            decisions = selector(selector_input)
            item = next(value for value in decisions if value["slot"] == "items")
            item["layout_kind"] = "overlay"
            item["main_axis"] = "none"
            item["evidence_ids"] = []
            return decisions

        with self.assertRaisesRegex(LayoutContractError, "overlay_evidence_required"):
            derive_component_layout(bound_page(), unsupported_overlay)

    def test_layout_output_contains_executable_reference_gap_relations(self):
        result = derive_component_layout(bound_page(), selector)
        gaps = [
            item
            for item in result["reference_assertions"]
            if item["kind"] == "sibling_gap"
        ]
        self.assertTrue(
            any(
                item["previous_instance_id"] == "card-a"
                and item["current_instance_id"] == "card-b"
                and item["axis"] == "vertical"
                and item["expected_gap"] == 16
                and item["measurement"] == "after_natural_layout"
                for item in gaps
            )
        )

    def test_constraint_expression_types_and_target_evidence_binding_fail_closed(self):
        def malformed_field(selector_input):
            decisions = selector(selector_input)
            item = next(value for value in decisions if value["slot"] == "items")
            evidence = next(value for value in selector_input["layout_evidence"] if value["kind"] == "sibling_relation")
            item["constraints"] = [
                {
                    "target": {
                        "kind": "gap",
                        "axis": "vertical",
                        "previous_instance_id": "card-a",
                        "current_instance_id": "card-b",
                    },
                    "expression": {
                        "op": "copy",
                        "evidence_id": evidence["evidence_id"],
                        "field": ["vertical_gap"],
                    },
                }
            ]
            return decisions

        with self.assertRaisesRegex(LayoutContractError, "constraint_expression_invalid"):
            derive_component_layout(bound_page(), malformed_field)

        def wrong_field(selector_input):
            decisions = selector(selector_input)
            item = next(value for value in decisions if value["slot"] == "items")
            evidence = next(value for value in selector_input["layout_evidence"] if value["kind"] == "sibling_relation")
            item["constraints"] = [
                {
                    "target": {
                        "kind": "gap",
                        "axis": "vertical",
                        "previous_instance_id": "card-a",
                        "current_instance_id": "card-b",
                    },
                    "expression": {
                        "op": "copy",
                        "evidence_id": evidence["evidence_id"],
                        "field": "order_relation",
                    },
                }
            ]
            return decisions

        with self.assertRaisesRegex(LayoutContractError, "constraint_evidence_target_mismatch"):
            derive_component_layout(bound_page(), wrong_field)

        def scalar_evidence_ids(selector_input):
            decisions = selector(selector_input)
            item = next(value for value in decisions if value["slot"] == "items")
            evidence = next(value for value in selector_input["layout_evidence"] if value["kind"] == "sibling_relation")
            item["constraints"] = [
                {
                    "target": {
                        "kind": "gap",
                        "axis": "vertical",
                        "previous_instance_id": "card-a",
                        "current_instance_id": "card-b",
                    },
                    "expression": {
                        "op": "nearest_gap",
                        "evidence_ids": evidence["evidence_id"],
                        "axis": "vertical",
                    },
                }
            ]
            return decisions

        with self.assertRaisesRegex(LayoutContractError, "constraint_expression_invalid"):
            derive_component_layout(bound_page(), scalar_evidence_ids)

    def test_unknown_constraint_op_and_non_member_target_fail_closed(self):
        def bad_op(selector_input):
            decisions = selector(selector_input)
            item = next(value for value in decisions if value["slot"] == "items")
            evidence = next(value for value in selector_input["layout_evidence"] if value["kind"] == "sibling_relation")
            item["constraints"] = [
                {
                    "target": {
                        "kind": "gap",
                        "axis": "vertical",
                        "previous_instance_id": "card-a",
                        "current_instance_id": "card-b",
                    },
                    "expression": {
                        "op": "multiply",
                        "evidence_id": evidence["evidence_id"],
                        "field": "vertical_gap",
                    },
                }
            ]
            return decisions

        with self.assertRaisesRegex(LayoutContractError, "constraint_expression_invalid"):
            derive_component_layout(bound_page(), bad_op)

        def non_member(selector_input):
            decisions = selector(selector_input)
            item = next(value for value in decisions if value["slot"] == "items")
            evidence = next(value for value in selector_input["layout_evidence"] if value["kind"] == "sibling_relation")
            item["constraints"] = [
                {
                    "target": {
                        "kind": "gap",
                        "axis": "vertical",
                        "previous_instance_id": "card-a",
                        "current_instance_id": "footer",
                    },
                    "expression": {
                        "op": "copy",
                        "evidence_id": evidence["evidence_id"],
                        "field": "vertical_gap",
                    },
                }
            ]
            return decisions

        with self.assertRaisesRegex(LayoutContractError, "constraint_target_invalid"):
            derive_component_layout(bound_page(), non_member)

    def test_overlay_requires_no_axis_and_preserves_non_overlap_for_other_pairs(self):
        page = bound_page()
        card_b = page["source_nodes_by_id"]["card-b-node"]
        card_b["frame"] = rect(16, 180, 358, 182)

        def overlay_with_axis(selector_input):
            decisions = selector(selector_input)
            item = next(value for value in decisions if value["slot"] == "items")
            item["layout_kind"] = "overlay"
            item["main_axis"] = "vertical"
            return decisions

        with self.assertRaisesRegex(LayoutContractError, "overlay_axis_invalid"):
            derive_component_layout(page, overlay_with_axis)

        third_block = {
            "block_id": "card-c-block",
            "semantic_parent_block_id": "content-block",
            "ordered_source_node_ids": ["card-c-node"],
            "rendering_source_node_ids": ["card-c-node"],
            "non_rendering_source_node_ids": [],
            "content_roles_by_source_node_id": {"card-c-node": "static_visual"},
        }
        page["blocks_by_id"]["card-c-block"] = third_block
        page["source_nodes_by_id"]["card-c-node"] = {
            "source_node_id": "card-c-node",
            "source_parent_node_id": "content-node",
            "source_order": 8,
            "frame": rect(16, 520, 358, 100),
            "real_frame": None,
            "geometry_basis": "frame",
            "frame_space": "artboard",
        }
        page["instances"].append(
            {
                "instance_id": "card-c",
                "component_id": "card-component",
                "parent_instance_id": "content",
                "slot": "items",
                "order": 2,
                "source_block_ids": ["card-c-block"],
            }
        )

        def valid_overlay(selector_input):
            decisions = selector(selector_input)
            item = next(value for value in decisions if value["slot"] == "items")
            item["layout_kind"] = "overlay"
            item["main_axis"] = "none"
            return decisions

        result = derive_component_layout(page, valid_overlay)
        group = next(
            item
            for item in result["responsive_assertions"]
            if item["kind"] == "no_unintended_overlap_group"
            and item["parent_instance_id"] == "content"
        )
        self.assertEqual(group["member_instance_ids"], ["card-a", "card-b", "card-c"])
        self.assertNotIn(["card-b", "card-c"], group["allowed_overlap_pairs"])
        self.assertNotIn(["card-a", "card-c"], group["allowed_overlap_pairs"])

    def test_multi_member_runtime_variable_layout_requires_an_axis(self):
        def none_axis(selector_input):
            decisions = selector(selector_input)
            item = next(value for value in decisions if value["scope"] == "slots")
            item["layout_kind"] = "constraint"
            item["main_axis"] = "none"
            return decisions

        with self.assertRaisesRegex(LayoutContractError, "layout_axis_required"):
            derive_component_layout(bound_page(), none_axis)

    def test_component_visual_envelope_includes_internal_block_overflow(self):
        page = bound_page()
        page["blocks_by_id"]["card-a-internal"] = {
            "block_id": "card-a-internal",
            "semantic_parent_block_id": "card-a-block",
            "ordered_source_node_ids": ["card-a-overflow"],
            "rendering_source_node_ids": ["card-a-overflow"],
            "non_rendering_source_node_ids": [],
            "content_roles_by_source_node_id": {"card-a-overflow": "static_visual"},
        }
        page["source_nodes_by_id"]["card-a-overflow"] = {
            "source_node_id": "card-a-overflow",
            "source_parent_node_id": "card-a-node",
            "source_order": 8,
            "frame": rect(370, 140, 30, 20),
            "real_frame": None,
            "geometry_basis": "frame",
            "frame_space": "artboard",
        }
        card_a = next(value for value in page["instances"] if value["instance_id"] == "card-a")
        card_a["source_block_ids"].append("card-a-internal")

        result = derive_component_layout(page, selector)
        geometry = result["component_geometry_by_instance_id"]["card-a"]
        self.assertEqual(geometry["artboard_envelope"]["left"], -4)
        self.assertEqual(geometry["artboard_envelope"]["width"], 404)
        self.assertIn("card-a-overflow", {item["source_node_id"] for item in geometry["owned_regions"]})

    def test_horizontal_scroll_overflow_permission_propagates_to_descendants(self):
        def horizontal_scroll(selector_input):
            decisions = selector(selector_input)
            item = next(
                value
                for value in decisions
                if value["scope"] == "slot"
                and value["parent_instance_id"] == "page"
                and value["slot"] == "body"
            )
            item["layout_kind"] = "scroll"
            item["main_axis"] = "horizontal"
            return decisions

        result = derive_component_layout(bound_page(), horizontal_scroll)
        scopes = [
            item
            for item in result["responsive_assertions"]
            if item["kind"] == "horizontal_overflow_scope"
        ]
        self.assertEqual(len(scopes), 1)
        self.assertEqual(
            set(scopes[0]["allowed_instance_ids"]),
            {"content", "card-a", "card-b"},
        )
        components = runtime_components(result)
        card_b = next(item for item in components if item["instance_id"] == "card-b")
        card_b["bounds"]["left"] = 420
        reachability = next(
            item
            for item in result["responsive_assertions"]
            if item["kind"] == "scroll_reachability"
        )
        forged_offsets = responsive_snapshot(
            components,
            scroll_metrics=[
                {
                    "decision_id": reachability["decision_id"],
                    "container_instance_id": reachability["container_instance_id"],
                    "axis": "horizontal",
                    "viewport_extent": 390,
                    "content_extent": 780,
                    "observed_offsets": [0, 390],
                }
            ],
            driver_observations={
                "observed_instance_ids": [
                    item["instance_id"] for item in components
                ],
                "scroll_actions": [
                    {
                        "axis": "horizontal",
                        "direction": "forward",
                        "start_px": {"x": 300, "y": 320},
                        "end_px": {"x": 100, "y": 320},
                    }
                ],
            },
        )
        rejected = verify_runtime_layout(result, forged_offsets, "responsive")
        self.assertIn(
            "runtime_scroll_unreachable",
            {item["code"] for item in rejected["failures"]},
        )

        checked = verify_runtime_layout(
            result,
            responsive_snapshot(
                components,
                scroll_metrics=forged_offsets["scroll_metrics"],
                driver_observations={
                    "observed_instance_ids": [
                        item["instance_id"] for item in components
                    ],
                    "scroll_actions": [
                        {
                            "axis": "horizontal",
                            "direction": "forward",
                            "start_px": {"x": 300, "y": 320},
                            "end_px": {"x": 100, "y": 320},
                        }
                    ],
                    "scroll_results": [
                        {
                            "decision_id": reachability["decision_id"],
                            "container_instance_id": reachability[
                                "container_instance_id"
                            ],
                            "axis": "horizontal",
                            "end_reached": True,
                            "restored_to_start": True,
                            "observed_instance_ids": [
                                item["instance_id"] for item in components
                            ],
                        }
                    ],
                },
            ),
            "responsive",
        )
        self.assertNotIn(
            "runtime_scroll_unreachable",
            {item["code"] for item in checked["failures"]},
        )
        self.assertNotIn("runtime_horizontal_overflow", {item["code"] for item in checked["failures"]})

    def test_component_graph_cycle_unreachable_and_root_parent_fail_closed(self):
        page = bound_page()
        root = next(value for value in page["instances"] if value["instance_id"] == "page")
        root["parent_instance_id"] = "content"
        with self.assertRaisesRegex(LayoutContractError, "component_tree_invalid"):
            derive_component_layout(page, selector)

        page = bound_page()
        page["component_definitions_by_id"]["cycle-component"] = {
            "component_id": "cycle-component",
            "kind": "container",
            "slots": [{"slot_id": "items", "role": "content", "cardinality": "many"}],
        }
        page["instances"].extend(
            [
                {
                    "instance_id": "cycle-a",
                    "component_id": "cycle-component",
                    "parent_instance_id": "cycle-b",
                    "slot": "items",
                    "order": 0,
                    "source_block_ids": [],
                },
                {
                    "instance_id": "cycle-b",
                    "component_id": "cycle-component",
                    "parent_instance_id": "cycle-a",
                    "slot": "items",
                    "order": 0,
                    "source_block_ids": [],
                },
            ]
        )
        with self.assertRaisesRegex(LayoutContractError, "component_tree_invalid"):
            derive_component_layout(page, selector)

    def test_malformed_selector_scalars_return_contract_errors_not_python_errors(self):
        def bad_sizing(selector_input):
            decisions = selector(selector_input)
            decisions[0]["sizing_policy"]["height"] = {"unexpected": True}
            return decisions

        with self.assertRaisesRegex(LayoutContractError, "layout_decision_schema_invalid"):
            derive_component_layout(bound_page(), bad_sizing)

        def bad_overflow(selector_input):
            decisions = selector(selector_input)
            decisions[0]["overflow_policy"] = []
            return decisions

        with self.assertRaisesRegex(LayoutContractError, "layout_decision_schema_invalid"):
            derive_component_layout(bound_page(), bad_overflow)

        def bad_decision_id(selector_input):
            decisions = selector(selector_input)
            decisions[0]["decision_id"] = []
            return decisions

        with self.assertRaisesRegex(LayoutContractError, "layout_decisions_invalid"):
            derive_component_layout(bound_page(), bad_decision_id)

    def test_non_rendering_block_wrapper_is_structural_and_uses_descendant_geometry(self):
        page = bound_page()
        content = next(value for value in page["instances"] if value["instance_id"] == "content")
        content["parent_instance_id"] = "semantic-wrapper"
        content["slot"] = "items"
        page["instances"].append(
            {
                "instance_id": "semantic-wrapper",
                "component_id": "content-component",
                "parent_instance_id": "page",
                "slot": "body",
                "order": 0,
                "source_block_ids": ["wrapper-semantic-block"],
            }
        )
        page["blocks_by_id"]["wrapper-semantic-block"] = {
            "block_id": "wrapper-semantic-block",
            "semantic_parent_block_id": "page-block",
            "ordered_source_node_ids": ["wrapper-semantic-node"],
            "rendering_source_node_ids": [],
            "non_rendering_source_node_ids": ["wrapper-semantic-node"],
            "content_roles_by_source_node_id": {"wrapper-semantic-node": "static_visual"},
        }
        page["source_nodes_by_id"]["wrapper-semantic-node"] = {
            "source_node_id": "wrapper-semantic-node",
            "source_parent_node_id": "root-node",
            "source_order": 8,
            "frame": None,
            "real_frame": None,
            "geometry_basis": "not_applicable",
            "frame_space": None,
        }

        result = derive_component_layout(page, selector)
        wrapper = result["component_geometry_by_instance_id"]["semantic-wrapper"]
        self.assertEqual(wrapper["geometry_source"], "descendant_union")
        self.assertEqual(wrapper["artboard_envelope"], rect(16, 104, 358, 620))

    def test_slot_sizing_is_based_on_members_not_parent_owned_text(self):
        page = bound_page()
        page["blocks_by_id"]["content-block"]["content_roles_by_source_node_id"]["content-node"] = "static_copy"
        page["blocks_by_id"]["card-a-block"]["content_roles_by_source_node_id"]["card-a-text"] = "static_visual"

        def intrinsic_items(selector_input):
            decisions = selector(selector_input)
            item = next(value for value in decisions if value["slot"] == "items")
            item["sizing_policy"]["height"] = "intrinsic"
            return decisions

        result = derive_component_layout(page, intrinsic_items)
        item = next(value for value in result["authored_layout_decisions"] if value["slot"] == "items")
        self.assertEqual(item["sizing_policy"]["height"], "intrinsic")

    def test_viewport_overflow_check_does_not_depend_on_parent_containment(self):
        page = bound_page()
        page["source_nodes_by_id"]["card-b-node"]["frame"] = rect(0, 302, 100, 182)
        page["source_nodes_by_id"]["card-b-icon"]["frame"] = rect(10, 330, 56, 56)
        page["source_nodes_by_id"]["card-b-icon"]["real_frame"] = rect(12, 332, 52, 52)
        result = derive_component_layout(page, selector)
        parent_child = next(
            item
            for item in result["layout_evidence"]
            if item["kind"] == "parent_child" and item["child_instance_id"] == "card-b"
        )
        self.assertNotEqual(parent_child["containment"], "contained")

        components = runtime_components(result)
        card_b = next(item for item in components if item["instance_id"] == "card-b")
        card_b["bounds"]["left"] = 350
        checked = verify_runtime_layout(
            result,
            responsive_snapshot(components),
            "responsive",
        )
        self.assertIn("runtime_horizontal_overflow", {item["code"] for item in checked["failures"]})

    def test_responsive_verifier_detects_unreachable_vertical_clipping(self):
        result = derive_component_layout(bound_page(), selector)
        components = runtime_components(result)
        footer = next(item for item in components if item["instance_id"] == "footer")
        footer["bounds"]["top"] = 620
        footer["bounds"]["height"] = 80

        checked = verify_runtime_layout(
            result,
            responsive_snapshot(components),
            "responsive",
        )

        self.assertIn(
            "runtime_vertical_clipping",
            {item["code"] for item in checked["failures"]},
        )

    def test_reference_overflow_is_an_allowance_not_a_whole_component_exemption(self):
        result = derive_component_layout(bound_page(), selector)
        allowance = next(
            item
            for item in result["responsive_assertions"]
            if item["kind"] == "horizontal_overflow_allowance"
            and item["instance_id"] == "card-a"
        )
        self.assertEqual(allowance["left"], 4)
        self.assertEqual(allowance["right"], 0)

        components = runtime_components(result)
        card_a = next(item for item in components if item["instance_id"] == "card-a")
        card_a["bounds"]["left"] = -5
        checked = verify_runtime_layout(
            result,
            responsive_snapshot(components),
            "responsive",
        )
        self.assertIn("runtime_horizontal_overflow", {item["code"] for item in checked["failures"]})

    def test_cross_slot_exact_gap_only_uses_adjacent_slot_boundary_members(self):
        page = bound_page()
        page["component_definitions_by_id"]["page-component"]["slots"][0]["cardinality"] = "many"
        page["source_nodes_by_id"]["body-extra-node"] = {
            "source_node_id": "body-extra-node",
            "source_parent_node_id": "root-node",
            "source_order": 8,
            "frame": rect(16, 730, 358, 20),
            "real_frame": None,
            "geometry_basis": "frame",
            "frame_space": "artboard",
        }
        page["blocks_by_id"]["body-extra-block"] = {
            "block_id": "body-extra-block",
            "semantic_parent_block_id": "page-block",
            "ordered_source_node_ids": ["body-extra-node"],
            "rendering_source_node_ids": ["body-extra-node"],
            "non_rendering_source_node_ids": [],
            "content_roles_by_source_node_id": {"body-extra-node": "static_visual"},
        }
        page["instances"].append(
            {
                "instance_id": "body-extra",
                "component_id": "card-component",
                "parent_instance_id": "page",
                "slot": "body",
                "order": 1,
                "source_block_ids": ["body-extra-block"],
            }
        )

        def body_then_footer(selector_input):
            decisions = selector(selector_input)
            body = next(item for item in decisions if item["scope"] == "slot" and item["slot"] == "body")
            body["main_axis"] = "vertical"
            cross = next(item for item in decisions if item["scope"] == "slots")
            cross["ordered_member_ids"] = ["body", "footer"]
            return decisions

        result = derive_component_layout(page, body_then_footer)
        page_gaps = [
            item
            for item in result["reference_assertions"]
            if item["kind"] == "sibling_gap"
            and item["parent_instance_id"] == "page"
            and item["relation_kind"] == "cross_slot_relation"
        ]
        self.assertEqual(
            [(item["previous_instance_id"], item["current_instance_id"], item["expected_gap"]) for item in page_gaps],
            [("body-extra", "footer", 10)],
        )

    def test_blockless_wrapper_paint_order_uses_visual_descendants(self):
        page = bound_page()
        page["component_definitions_by_id"]["wrapper-component"] = {
            "component_id": "wrapper-component",
            "kind": "container",
            "slots": [{"slot_id": "content", "role": "content", "cardinality": "one"}],
        }
        content = next(item for item in page["instances"] if item["instance_id"] == "content")
        content["parent_instance_id"] = "wrapper"
        content["slot"] = "content"
        page["instances"].append(
            {
                "instance_id": "wrapper",
                "component_id": "wrapper-component",
                "parent_instance_id": "page",
                "slot": "body",
                "order": 0,
                "source_block_ids": [],
            }
        )
        page["source_nodes_by_id"]["footer-node"]["frame"] = rect(16, 700, 358, 90)

        result = derive_component_layout(page, selector)
        paint = next(
            item
            for item in result["layout_evidence"]
            if item["kind"] == "source_paint_order"
            and {item["first_instance_id"], item["second_instance_id"]} == {"wrapper", "footer"}
        )
        self.assertEqual(paint["painted_later_instance_id"], "footer")
        wrapper_refs = paint["source_references"]["second" if paint["second_instance_id"] == "wrapper" else "first"]
        self.assertIn("content-node", wrapper_refs["source_node_ids"])

    def test_non_overlapping_large_group_does_not_emit_quadratic_pair_evidence(self):
        page = bound_page()
        count = 120
        for index in range(count):
            node_id = f"extra-node-{index}"
            block_id = f"extra-block-{index}"
            instance_id = f"extra-{index}"
            page["source_nodes_by_id"][node_id] = {
                "source_node_id": node_id,
                "source_parent_node_id": "content-node",
                "source_order": 8 + index,
                "frame": rect(16, 500 + index * 12, 358, 10),
                "real_frame": None,
                "geometry_basis": "frame",
                "frame_space": "artboard",
            }
            page["blocks_by_id"][block_id] = {
                "block_id": block_id,
                "semantic_parent_block_id": "content-block",
                "ordered_source_node_ids": [node_id],
                "rendering_source_node_ids": [node_id],
                "non_rendering_source_node_ids": [],
                "content_roles_by_source_node_id": {node_id: "static_visual"},
            }
            page["instances"].append(
                {
                    "instance_id": instance_id,
                    "component_id": "card-component",
                    "parent_instance_id": "content",
                    "slot": "items",
                    "order": 2 + index,
                    "source_block_ids": [block_id],
                }
            )

        result = derive_component_layout(page, selector)
        paint_evidence = [item for item in result["layout_evidence"] if item["kind"] == "source_paint_order"]
        self.assertEqual(paint_evidence, [])
        self.assertLess(len(result["layout_evidence"]), count * 8)
        groups = [item for item in result["responsive_assertions"] if item["kind"] == "no_unintended_overlap_group"]
        self.assertEqual(len(groups), 2)

    def test_root_region_provenance_uses_block_that_owns_root_source_node(self):
        page = bound_page()
        root = next(item for item in page["instances"] if item["instance_id"] == "page")
        root["source_block_ids"].insert(0, "header-block")
        page["source_nodes_by_id"]["header-node"] = {
            "source_node_id": "header-node",
            "source_parent_node_id": "root-node",
            "source_order": 8,
            "frame": rect(0, 0, 390, 80),
            "real_frame": None,
            "geometry_basis": "frame",
            "frame_space": "artboard",
        }
        page["blocks_by_id"]["header-block"] = {
            "block_id": "header-block",
            "semantic_parent_block_id": "page-block",
            "ordered_source_node_ids": ["header-node"],
            "rendering_source_node_ids": ["header-node"],
            "non_rendering_source_node_ids": [],
            "content_roles_by_source_node_id": {"header-node": "static_visual"},
        }

        result = derive_component_layout(page, selector)
        root_region = result["component_geometry_by_instance_id"]["page"]["boundary_regions"][0]
        self.assertEqual(root_region["block_id"], "page-block")
        self.assertEqual(result["component_geometry_by_instance_id"]["page"]["boundary_block_ids"], ["page-block"])

    def test_decision_obligations_index_global_evidence_once(self):
        result = derive_component_layout(bound_page(), selector)

        class CountingEvidence(list):
            iterations = 0

            def __iter__(self):
                self.iterations += 1
                return super().__iter__()

        evidence = CountingEvidence(result["layout_evidence"])
        obligations = layout_module._decision_obligations(result["component_tree"], evidence)
        self.assertTrue(obligations)
        self.assertEqual(evidence.iterations, 1)

    def test_overlap_scan_selects_axis_that_avoids_quadratic_vertical_checks(self):
        count = 200
        member_ids = [f"row-{index}" for index in range(count)]
        geometry = {
            instance_id: {"artboard_envelope": rect(16, index * 12, 358, 10)}
            for index, instance_id in enumerate(member_ids)
        }
        real_intersection = layout_module._intersection
        calls = 0

        def counted(first, second):
            nonlocal calls
            calls += 1
            return real_intersection(first, second)

        with patch.object(layout_module, "_intersection", side_effect=counted):
            self.assertEqual(layout_module._overlapping_pairs(member_ids, geometry), [])
        self.assertLess(calls, count * 2)

    def test_canvas_nodes_require_a_canvas_space_root(self):
        page = bound_page()
        root = page["source_nodes_by_id"]["root-node"]
        root["frame"] = rect(0, 0, 390, 886)
        root["frame_space"] = "artboard"
        page["source_nodes_by_id"]["content-node"]["frame_space"] = "canvas"
        with self.assertRaisesRegex(LayoutContractError, "source_frame_space_invalid"):
            derive_component_layout(page, selector)

    def test_union_non_rect_and_overdeep_expression_fail_with_contract_errors(self):
        def union_non_rect(selector_input):
            decisions = selector(selector_input)
            item = next(value for value in decisions if value["slot"] == "items")
            evidence = next(value for value in selector_input["layout_evidence"] if value["kind"] == "sibling_relation")
            item["constraints"] = [
                {
                    "target": {
                        "kind": "overlap",
                        "first_instance_id": "card-a",
                        "second_instance_id": "card-b",
                    },
                    "expression": {
                        "op": "union",
                        "evidence_ids": [evidence["evidence_id"]],
                        "field": "source_references",
                    },
                }
            ]
            return decisions

        with self.assertRaisesRegex(LayoutContractError, "constraint_evidence_invalid"):
            derive_component_layout(bound_page(), union_non_rect)

        def overdeep(selector_input):
            decisions = selector(selector_input)
            item = next(value for value in decisions if value["slot"] == "items")
            evidence = next(value for value in selector_input["layout_evidence"] if value["kind"] == "sibling_relation")
            base = {"op": "copy", "evidence_id": evidence["evidence_id"], "field": "vertical_gap"}
            expression = base
            for _ in range(80):
                expression = {"op": "add", "args": [expression, base]}
            item["constraints"] = [
                {
                    "target": {
                        "kind": "gap",
                        "axis": "vertical",
                        "previous_instance_id": "card-a",
                        "current_instance_id": "card-b",
                    },
                    "expression": expression,
                }
            ]
            return decisions

        with self.assertRaisesRegex(LayoutContractError, "constraint_expression_too_deep"):
            derive_component_layout(bound_page(), overdeep)

    def test_malformed_geometry_containers_and_partitions_fail_closed(self):
        page = bound_page()
        page["component_definitions_by_id"]["page-component"]["slots"] = 1
        with self.assertRaisesRegex(LayoutContractError, "component_definitions_invalid"):
            derive_component_layout(page, selector)

        page = bound_page()
        page["reference"]["coordinate_contract"]["supported_frame_spaces"] = ["canvas", "artboard", {}]
        with self.assertRaisesRegex(LayoutContractError, "source_coordinate_contract_invalid"):
            derive_component_layout(page, selector)

        page = bound_page()
        page["blocks_by_id"]["card-a-block"]["ordered_source_node_ids"].append({"bad": "node"})
        with self.assertRaisesRegex(LayoutContractError, "block_geometry_invalid"):
            derive_component_layout(page, selector)

        page = bound_page()
        page["blocks_by_id"]["card-a-block"]["rendering_source_node_ids"].append("card-a-node")
        with self.assertRaisesRegex(LayoutContractError, "block_geometry_invalid"):
            derive_component_layout(page, selector)

        page = bound_page()
        page["reference"]["logical_artboard_size"]["left"] = 999
        with self.assertRaisesRegex(LayoutContractError, "source_coordinate_contract_invalid"):
            derive_component_layout(page, selector)

    def test_nested_forbidden_fields_and_non_json_error_details_fail_closed(self):
        page = bound_page()
        page["platform_context"]["ui_description"] = "must not reach selector"
        with self.assertRaisesRegex(LayoutContractError, "stage_boundary_violation"):
            derive_component_layout(page, selector)

        def non_json_target(selector_input):
            decisions = selector(selector_input)
            item = next(value for value in decisions if value["slot"] == "items")
            item["constraints"] = [{"target": {"kind": b"gap"}, "expression": {"op": "copy"}}]
            return decisions

        with self.assertRaisesRegex(LayoutContractError, "constraint_target_invalid"):
            derive_component_layout(bound_page(), non_json_target)

        page = bound_page()
        page["source_nodes_by_id"]["card-a-node"]["frame"]["width"] = 10**400
        with self.assertRaisesRegex(LayoutContractError, "source_frame_invalid"):
            derive_component_layout(page, selector)

    def test_runtime_verifier_rejects_malformed_contract_and_snapshot_structurally(self):
        with self.assertRaisesRegex(LayoutContractError, "runtime_contract_invalid"):
            verify_runtime_layout({}, {"components": []}, "reference")

        result = derive_component_layout(bound_page(), selector)
        checked = verify_runtime_layout(
            result,
            responsive_snapshot(
                [{"instance_id": [], "bounds": rect(0, 0, 1, 1)}]
            ),
            "responsive",
        )
        self.assertIn("runtime_component_invalid", {item["code"] for item in checked["failures"]})

    def test_runtime_verifier_rejects_authored_pass_fail_flags(self):
        result = derive_component_layout(bound_page(), selector)
        snapshot = responsive_snapshot(runtime_components(result))
        snapshot["no_clip"] = True

        checked = verify_runtime_layout(result, snapshot, "responsive")

        self.assertIn(
            "runtime_self_certification_forbidden",
            {item["code"] for item in checked["failures"]},
        )

    def test_same_block_internal_renderer_overflow_is_in_visual_envelope(self):
        page = bound_page()
        page["source_nodes_by_id"]["card-a-inner-overflow"] = {
            "source_node_id": "card-a-inner-overflow",
            "source_parent_node_id": "card-a-node",
            "source_order": 8,
            "frame": rect(370, 140, 30, 20),
            "real_frame": None,
            "geometry_basis": "frame",
            "frame_space": "artboard",
        }
        block = page["blocks_by_id"]["card-a-block"]
        block["ordered_source_node_ids"].append("card-a-inner-overflow")
        block["rendering_source_node_ids"].append("card-a-inner-overflow")
        block["content_roles_by_source_node_id"]["card-a-inner-overflow"] = "static_visual"

        result = derive_component_layout(page, selector)
        geometry = result["component_geometry_by_instance_id"]["card-a"]
        self.assertEqual(geometry["artboard_envelope"]["width"], 404)
        self.assertIn("card-a-inner-overflow", {item["source_node_id"] for item in geometry["owned_regions"]})

    def test_overdeep_closed_input_fails_as_a_structured_contract_error(self):
        page = bound_page()
        nested = {}
        cursor = nested
        for _ in range(1200):
            child = {}
            cursor["child"] = child
            cursor = child
        page["harmless_extension"] = nested

        with self.assertRaises(LayoutContractError) as raised:
            derive_component_layout(page, selector)

        self.assertEqual(raised.exception.code, "layout_input_too_deep")

if __name__ == "__main__":
    unittest.main()
