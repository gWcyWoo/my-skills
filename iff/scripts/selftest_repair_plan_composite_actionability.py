#!/usr/bin/env python3
from make_repair_plan import (
    actionability_fingerprint,
    annotate_actionability,
    implementation_hints,
    route_composite_asset_action,
    select_top_action,
)


def composite_node97() -> dict:
    return {
        "priority": "P0",
        "category": "asset_region",
        "node": "97:194",
        "observed": {"bbox": [50, 257, 650, 368], "pixelMismatch": 0.1234},
        "actualTrace": {"rect": {"x": 50, "y": 257, "width": 650, "height": 368}},
        "implementationHints": [],
        "diagnostic": {"confidence": "high", "note": "Runtime bbox is present."},
    }


def main() -> int:
    generated_map = {
        "nodeMappings": [
            {
                "node": "97:194",
                "bbox": [50, 257, 650, 368],
                "implementation": "image_png",
                "widget": "lib/generated/home.dart",
                "renderMode": "absolute_positioned",
            },
            {
                "node": "97:194:rendered-child",
                "bbox": [90, 290, 240, 180],
                "implementation": "image_png",
                "widget": "lib/generated/home.dart",
                "renderMode": "absolute_positioned",
            },
        ]
    }
    parent_hints = implementation_hints(generated_map, "97:194", None)
    child_hints = implementation_hints(generated_map, "97:194:rendered-child", None)
    assert parent_hints[0]["generatedValueKey"] == "iff:97:194", parent_hints
    assert child_hints[0]["generatedValueKey"] == "iff:97:194:rendered-child", child_hints
    rejected = route_composite_asset_action(
        composite_node97(),
        [{"node": "97:194:rendered-child", "area": 5184, "implementationHints": []}],
    )
    rejected = annotate_actionability([rejected])[0]
    assert rejected["node"] == "97:194", rejected
    assert rejected["repairEligibility"]["eligible"] is False, rejected
    assert "missing_deterministic_source_binding" in rejected["repairEligibility"]["reasons"], rejected
    assert "composite_asset_lacks_isolation_or_source_evidence" in rejected["repairEligibility"]["reasons"], rejected

    source_bound_composite = composite_node97()
    source_bound_composite["implementationHints"] = parent_hints
    routed = route_composite_asset_action(
        source_bound_composite,
        [
            {
                "node": "97:194:rendered-child",
                "role": "heroArtwork",
                "component": "Region18",
                "widget": {"node": "97:194:rendered-child", "bbox": [90, 290, 240, 180]},
                "actualTrace": {"rect": {"x": 90, "y": 290, "width": 240, "height": 180}},
                "implementationHints": child_hints,
                "area": 43200,
            }
        ],
    )
    independent = {
        "priority": "P1",
        "category": "asset_region",
        "node": "17:158",
        "actualTrace": {"rect": {"x": 700, "y": 123, "width": 72, "height": 72}},
        "implementationHints": [{"file": "lib/generated/home.dart", "valueKey": "design-node-17-158"}],
        "diagnostic": {"confidence": "high", "note": "Source-bound asset."},
        "assetIsolation": {"isolated": True, "overlappingNodeCount": 0, "sourceBackedOverlapCount": 0},
    }
    actions = annotate_actionability([rejected, routed, independent])
    top = select_top_action(actions)
    assert top is not None, actions
    assert top["node"] == "17:158", top
    routed_action = actions[1]
    assert routed_action["repairEligibility"]["eligible"] is False, routed_action
    assert "composite_parent_metrics_are_not_child_local_evidence" in routed_action[
        "repairEligibility"
    ]["reasons"], routed_action
    changed_metrics = routed_action.copy()
    changed_metrics["observed"] = {"bbox": [50, 257, 650, 368], "pixelMismatch": 0.2}
    changed_metrics["score"] = 999999
    assert actionability_fingerprint(changed_metrics) == actionability_fingerprint(routed_action)
    assert routed_action["repairEligibility"]["evidence"]["sourceBindingFingerprint"], routed_action
    print("OK: composite parent metrics cannot drive a child edit; an independent source-bound action wins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
