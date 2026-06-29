#!/usr/bin/env python3
"""Create the exact prompt used to spawn one iFF worker."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_row(path: str | None) -> dict:
    if not path:
        return {}
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--row-json", help="One claimed CSV/Excel row serialized as JSON.")
    parser.add_argument("--spec-dir", required=True)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    skill_dir = Path(args.skill_dir).expanduser().resolve()
    skill_md = skill_dir / "SKILL.md"
    test_rules = skill_dir / "test_rules.md"
    scripts_dir = skill_dir / "scripts"
    required = [skill_md, test_rules, scripts_dir / "verify_pipeline_scripts.py"]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("ERROR: worker prompt inputs missing:\n" + "\n".join(missing))

    row = load_row(args.row_json)
    hashes = {
        "skill_md_sha256": digest(skill_md),
        "test_rules_sha256": digest(test_rules),
        "verify_pipeline_scripts_sha256": digest(scripts_dir / "verify_pipeline_scripts.py"),
    }
    prompt = f"""IFF_WORKER_BOOTSTRAP v1
You are one iFF worker for exactly one claimed row. EXECUTE this pipeline by RUNNING TOOLS
(Bash / Read / Edit / Write / MCP). Do NOT reply with prose, do NOT ask the user questions, do
NOT merely describe a plan — actually run each step. Your ONLY stopping point is printing the
final result summary after the done-audit gates (or a concrete failure summary if blocked).
Do not rely on automatic skill loading. You are not alone in this codebase: do not revert edits
made by others, and adjust your implementation to accommodate current files.

Your FIRST action MUST be this Bash command (run it NOW), then continue top-to-bottom:
1. Run: python3 {scripts_dir / "verify_pipeline_scripts.py"} --skill-dir {skill_dir}
2. Read {skill_md} completely (the fixed pipeline you must follow, steps 0–12).
3. Read {test_rules} completely.
4. Write {Path(args.spec_dir) / "worker_compliance.json"} with:
   - loaded_files: [{str(skill_md)!r}, {str(test_rules)!r}]
   - skill_md_sha256: {hashes["skill_md_sha256"]}
   - test_rules_sha256: {hashes["test_rules_sha256"]}
   - verify_pipeline_scripts_sha256: {hashes["verify_pipeline_scripts_sha256"]}
   - pipeline_scripts_ok: true
   - worker_bootstrap_version: IFF_WORKER_BOOTSTRAP v1

Hard gates:
- Follow the fixed iFF pipeline from SKILL.md; do not skip or merge steps.
- Use only scripts under {scripts_dir} for deterministic artifacts.
- Treat raw.json as Lanhu-wrapped Figma JSON. The primary design compiler is export_figma_scene.py -> check_figma_scene.py -> group_figma_layout.py -> make_figma_layout_contract.py. Do not use generic JSON walking or bbox/name guessing as the main source of truth for complex designs.
- Compile interaction into contract/test plan and prove coverage with red/green evidence.
- Implement UI from scene/tokens/assets/layout/render/interaction contracts, not from visual guesswork.
- Never use the full design reference as a widget background or visible layer.
- After runtime screenshot diff, generate repair_plan.json and apply it at most once. Re-capture and re-diff once after that repair. If the page still misses visual thresholds, return a failure summary instead of iterating; the main session will mark the row error and move to the next requirement.
- Before implementation planning, run: python3 {scripts_dir / "check_design_artifacts.py"} --spec-dir {Path(args.spec_dir).resolve()}
- Before writing tests or production code, write {Path(args.spec_dir) / "implementation_plan.json"} and run: python3 {scripts_dir / "check_implementation_plan.py"} --plan {Path(args.spec_dir) / "implementation_plan.json"} --spec-dir {Path(args.spec_dir).resolve()}
- Return paths for spec_dir, worker_compliance.json, implementation_plan.json, interaction_test_evidence.json, visual_manifest.json, actual.png, diff_report.json, and any required dependency/route/DI/asset registrations.

Planning gate:
- Read the current project entrypoint and existing architecture just enough to choose project-local names and ownership boundaries.
- Read the current spec artifacts by schema as they exist on disk: design_classification.json, scene.json, groups.json, tokens.json, assets_manifest.json, layout_contract.json, render_plan.json, design_artifacts_report.json, interaction_contract.json, and interaction_test_plan.json.
- implementation_plan.json must include: artifactInventory counts and schema keys; scene.sourceSchema and Figma artboard id/path data; artboard and viewport sizes; variant states and the runtime fixture state count; Figma hierarchy layout regions from layout_contract.json; requiredVisibleNodeCount, textNodeCount, imageNodeCount, shapeNodeCount, assetAtomicNodes, coveredNodes, renderImplementationTypes; nodeCoveragePlan or regionNodeCoverage for visible render_plan nodes; coordinateRenderStrategy for a single scaled artboard Stack driven by render_plan bboxes; render strategy for image/text/shape/container nodes; asset copy/register plan; interaction case scope; projectSurface with entrypoint/app shell/feature dirs found or missing; fanoutOwnedFiles; faninRequests for shared files; implementation_map and actual_layout_trace strategy; screenshot/diff commands; singleRepairBudget:1 with post_repair_diff_report output; and forbidden shortcuts.
- For variant_board designs, plan every state group as runtime data, widget test data, and preview data from one fixture source. A plan with fewer runtime states than the design states is invalid.
- implementation_map.json must map visible render_plan nodes, not just layout regions. Before returning success, run: python3 {scripts_dir / "check_implementation_map.py"} --render-plan {Path(args.spec_dir) / "render_plan.json"} --implementation-map {Path(args.spec_dir) / "implementation_map.json"}
- Each visible-node entry in implementation_map.json must include node, implementation, widget, bbox, and renderMode:"absolute_positioned" (or positioning/layoutMode with the same explicit coordinate meaning). Component ownership without a render-plan bbox mode is invalid.
- Treat render_plan implementation values literally: image/image_png/image_webp/svg/asset nodes are atomic; do not also draw their descendants. image_fill must render the Figma image fill instead of a placeholder. gradient_shape must preserve gradient stops. vector_shape and shape_container must use Figma bbox/fill/border/radius/shadow/effects. clip_group and mask_group must preserve clipping/mask semantics. covered_by_asset and covered_by_text nodes are not visible widgets. text nodes must render the exact text string from scene/render data, not black boxes. oval_shape nodes must render as ovals, not rectangular bbox fills.
- For screenshot fidelity, the visible layer must be an absolute render-plan canvas: scale the artboard to runtime viewport units, place every visible node at its render_plan bbox with Positioned/CustomPaint/Image/Text equivalents, and preserve design x/y/width/height. Do not rebuild visible card/support/tab regions with Row/Column/Flex spacing or semantic component templates. Semantic widgets are allowed only as transparent hit areas or behavior adapters over the coordinate-rendered pixels.
- If the row asks for paths that do not exist in the current project, do not pretend they exist. Plan the smallest project-consistent scaffold and list shared-file edits for serial fan-in.
- If an artifact schema differs from SKILL.md wording, follow the actual artifact schema and record the mismatch in implementation_plan.json instead of guessing fields.

Row JSON:
{json.dumps(row, ensure_ascii=False, indent=2)}

Project root: {Path(args.project_root).resolve()}
Spec dir: {Path(args.spec_dir).resolve()}
"""
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(prompt, encoding="utf-8")
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
