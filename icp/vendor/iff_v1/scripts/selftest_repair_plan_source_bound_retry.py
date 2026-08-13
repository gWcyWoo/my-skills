#!/usr/bin/env python3
from make_repair_plan import (
    actionability_fingerprint,
    annotate_actionability,
    build_actionability_proof,
    implementation_hints,
    select_top_action,
    structural_delta,
)


def main() -> int:
    generated_map = {
        "nodeMappings": [
            {
                "node": "17:158",
                "implementation": "image_png",
                "widget": "lib/generated/home_canvas.dart",
                "bbox": [700, 123, 72, 72],
                "renderMode": "absolute_positioned",
            }
        ]
    }
    assert structural_delta(
        {"bbox": [415, 481.5, 237, 61], "text": "Daily Interest Rate: < 0.05%", "fontSize": 24},
        {"bbox": [415, 481.5, 237, 61], "text": "Daily Interest Rate: < 0.05%", "fontSize": None},
    ) == {}
    asset_hints = implementation_hints(generated_map, "17:158", None)
    assert len(asset_hints) == 1, asset_hints
    assert asset_hints[0]["generatedValueKey"] == "iff:17:158", asset_hints

    source_bound_pixel_text = {
        "priority": "P0",
        "category": "text_region",
        "node": "17:266",
        "actualTrace": {"bbox": [85, 398, 280, 78], "text": "₦50,000", "fontSize": 65},
        "implementationHints": [
            {
                "node": "17:266",
                "implementation": "text",
                "widget": "lib/generated/home_canvas.dart",
                "bbox": [85, 398, 280, 78],
                "renderMode": "absolute_positioned",
            }
        ],
        "structuralDelta": {},
        "diagnostic": {"kind": "pixel_region", "confidence": "low", "note": "Pixel residual only."},
    }
    source_bound_asset = {
        "priority": "P1",
        "category": "asset_region",
        "node": "17:158",
        "actualTrace": {"rect": {"x": 700, "y": 123, "width": 72, "height": 72}},
        "implementationHints": asset_hints,
        "assetIsolation": {"isolated": True, "overlappingNodeCount": 0, "sourceBackedOverlapCount": 0},
        "diagnostic": {"confidence": "high", "note": "Generated source binding exists."},
    }
    actions = annotate_actionability([source_bound_pixel_text, source_bound_asset])
    assert actions[0]["repairEligibility"]["eligible"] is False, actions[0]
    assert "text_pixel_residual_has_no_structural_delta" in actions[0]["repairEligibility"]["reasons"], actions[0]
    top = select_top_action(actions)
    assert top is not None, actions
    assert top["node"] == "17:158", top
    proof = build_actionability_proof(actions, top)
    assert proof["eligible"] is True, proof
    assert proof["sourceBacked"] is True, proof
    assert proof["sourceBindingFingerprint"], proof
    assert select_top_action(actions, {actionability_fingerprint(top)}) is None
    print("OK: source-bound text pixel residual without structural delta is skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
