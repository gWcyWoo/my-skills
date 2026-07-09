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
    parser.add_argument("--spec-dir", required=True,
                        help="board mode: the ONE board dir; fetch/assembly mode: the feature spec root")
    parser.add_argument("--mode", choices=["assembly", "board", "fetch"], default="assembly",
                        help="board-level fan-out roles: fetch = run pipeline steps 0-3 scripts per board; "
                             "board = compile ONE board's visual unit (canvas/expected/slots/trace-test); "
                             "assembly = per-feature integration, interactions, TDD, device window, audits")
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

    shared_section = ""
    shared_local = Path(args.spec_dir) / "shared_components.local.json"
    # assembly mode gets the feature spec ROOT: aggregate every board's local file.
    components_all = []
    for local_file in ([shared_local] if shared_local.is_file()
                       else sorted(Path(args.spec_dir).glob("*/shared_components.local.json"))):
        shared = json.loads(local_file.read_text(encoding="utf-8"))
        components_all.extend(shared.get("components") or [])
    if True:
        components = components_all
        if components:
            shared_section = f"""
Shared components (pre-resolved by the main session — READ-ONLY reuse):
{json.dumps(components, ensure_ascii=False, indent=2)}
- Run make_render_plan.py with --shared {shared_local}; the listed group subtrees become covered_by_shared_component and must NOT be re-drawn on the canvas.
- Mount each status=reuse widget (widget_path/name above) at its group bbox as the visible layer for that region.
- NEVER create, edit, or fork shared component files during fan-out. If a shared-region visual issue shows up in diff, report it for serial fan-in; do not spend the single repair budget on it.
- A status=missing entry here means the main session failed to resolve it before spawn: stop and return a failure summary instead of re-implementing it locally.
"""

    hashes = {
        "skill_md_sha256": digest(skill_md),
        "test_rules_sha256": digest(test_rules),
        "verify_pipeline_scripts_sha256": digest(scripts_dir / "verify_pipeline_scripts.py"),
    }
    spec = Path(args.spec_dir).resolve()
    bootstrap = f"""Your FIRST action MUST be this Bash command (run it NOW), then continue top-to-bottom:
1. Run: python3 {scripts_dir / "verify_pipeline_scripts.py"} --skill-dir {skill_dir}
2. Read {skill_md} completely, then {test_rules}.
3. Write {spec / "worker_compliance.json"} with loaded_files, skill_md_sha256: {hashes["skill_md_sha256"]}, test_rules_sha256: {hashes["test_rules_sha256"]}, verify_pipeline_scripts_sha256: {hashes["verify_pipeline_scripts_sha256"]}, pipeline_scripts_ok: true, worker_bootstrap_version: IFF_WORKER_BOOTSTRAP v1."""

    if args.mode == "fetch":
        prompt = f"""IFF_FETCH_WORKER v1
You fetch + compile design boards for ONE sheet row. EXECUTE by RUNNING TOOLS; no prose, no questions.
{bootstrap}
For EACH board in Row JSON (split design_url on ASCII/full-width semicolons and newlines; one URL = one board),
into {spec}/<board-title>/ run pipeline steps 1->0->2->3 EXACTLY as SKILL.md commands:
fetch.py + write.py + download_cover.py -> classify_design.py -> export_figma_scene.py + check_figma_scene.py + export_tokens.py + export_assets_manifest.py -> group_figma_layout.py.
Rules: scripts from {scripts_dir} ONLY; zero model judgment beyond error reporting; NEVER read artifact file contents; one board failing must not stop the others (record its error, continue); do not run step 4+ (render_plan waits for shared-component detection).
Return a JSON summary: [{{"board": ..., "ok": true|false, "error": ...}}] per board.

Row JSON:
{json.dumps(row, ensure_ascii=False, indent=2)}

Project root: {Path(args.project_root).resolve()}
Feature spec root: {spec}
"""
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(prompt, encoding="utf-8")
        print(str(out))
        return 0

    if args.mode == "board":
        shared_local = spec / "shared_components.local.json"
        prompt = f"""IFF_BOARD_WORKER v1
You compile ONE design board's visual unit for feature <feature> (derive from the spec path). EXECUTE by RUNNING TOOLS; no prose, no questions. Sibling board workers run in parallel — touch ONLY this board's files.
{bootstrap}
Steps for THIS board ({spec}):
1. python3 {scripts_dir / "summarize_spec_artifacts.py"} --spec-dir {spec} ; read ONLY artifact_digest.json (reading discipline: big JSONs are script-consumed; window by node id when a single node is needed).
2. Step 4 commands: make_figma_layout_contract.py, then make_render_plan.py WITH --shared {shared_local} (must exist; a status=missing entry there means the main session failed to resolve shared components — STOP and return failure), then check_design_artifacts.py.
3. Step 6.7 commands: make_component_manifest.py then generate_canvas.py -> lib/<feature>/presentation/<state>_canvas.dart (+ .expected.json/.slots.json). copy_assets.py for this board's assets (FILES only — pubspec/fonts registration belongs to assembly).
4. python3 {scripts_dir / "merge_shared_expected.py"} --expected <canvas>.dart.expected.json --local {shared_local} --scene {spec / "scene.json"} --out {spec / "merged_expected.json"}
5. Write {spec / "implementation_map.json"} mapping this board's required render_plan nodes (renderMode absolute_positioned), then run check_implementation_map.py.
Allowed writes: lib/<feature>/presentation/<state>_canvas.dart{{,.expected.json,.slots.json}}, assets file copies, everything under {spec}. FORBIDDEN: page/selector/colors/fixture/slot-mapper or any feature-shared dart, routes/DI/pubspec/l10n, trace tests, ANY `flutter test`/`flutter run` (the assembly worker owns all test invocations), any other board's files.
Return: {{"board": ..., "canvas": ..., "expected": ..., "slots": ..., "mergedExpected": ..., "assets": [...], "ok": true|false}}.

Row JSON:
{json.dumps(row, ensure_ascii=False, indent=2)}

Project root: {Path(args.project_root).resolve()}
Spec dir: {spec}
"""
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(prompt, encoding="utf-8")
        print(str(out))
        return 0

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
- ASSEMBLY role (board-level fan-out): board workers already produced each state's canvas/expected/slots/merged_expected/implementation_map — CONSUME them, never regenerate or edit board canvases. You own: selector/page/colors/one shared fixture/slot mapper, interaction contract + state machine + anchors, prefill plan + modelFields, TDD (ONE red run, ONE green run), data integration, the device window (9-11, device_lock held), audits (12) with trace tests for every state generated by you and executed inside the ONE audit-time `flutter test`, and pubspec/fonts/asset registration for this feature's collected assets.
- Before writing done evidence, run: python3 {scripts_dir / "check_done_gate.py"} --spec-root {Path(args.spec_dir).resolve()} — its failures are yours to fix, not to explain away.
- Use only scripts under {scripts_dir} for deterministic artifacts.
- Treat raw.json as Lanhu-wrapped Figma JSON. The primary design compiler is export_figma_scene.py -> check_figma_scene.py -> group_figma_layout.py -> make_figma_layout_contract.py. Do not use generic JSON walking or bbox/name guessing as the main source of truth for complex designs.
- Compile interaction into contract/test plan and prove coverage with red/green evidence.
- Implement UI from scene/tokens/assets/layout/render/interaction contracts, not from visual guesswork.
- Never use the full design reference as a widget background or visible layer.
- The device window (install/launch/screenshot through the post-repair re-capture) is mutex-guarded: run device_lock.py acquire before the first device use and device_lock.py release on EVERY exit path (success, failure, error). Everything else runs in parallel with sibling workers.
- After runtime screenshot diff, generate repair_plan.json and apply it at most once. Re-capture and re-diff once after that repair. If the page still misses visual thresholds, return a failure summary instead of iterating; the main session will mark the row error and move to the next requirement.
- Before implementation planning, run: python3 {scripts_dir / "check_design_artifacts.py"} --spec-dir {Path(args.spec_dir).resolve()}
- Before writing tests or production code: run python3 {scripts_dir / "summarize_spec_artifacts.py"} --spec-dir {Path(args.spec_dir).resolve()} then python3 {scripts_dir / "prefill_implementation_plan.py"} --spec-dir {Path(args.spec_dir).resolve()}, fill ONLY the __MODEL__ placeholders listed in modelFields (never restate or edit machine-prefilled counts), then run: python3 {scripts_dir / "check_implementation_plan.py"} --plan {Path(args.spec_dir) / "implementation_plan.json"} --spec-dir {Path(args.spec_dir).resolve()}
- Return paths for spec_dir, worker_compliance.json, implementation_plan.json, interaction_test_evidence.json, visual_manifest.json, actual.png, diff_report.json, and any required dependency/route/DI/asset registrations.

Planning gate:
- Read the current project entrypoint and existing architecture just enough to choose project-local names and ownership boundaries.
- Reading discipline (token budget is part of correctness): run summarize_spec_artifacts.py first and read spec_dir/artifact_digest.json — it carries every artifact's schema keys, counts, case ids, endpoints and shared components. NEVER read scene.json, render_plan.json, layout_contract.json, repair_plan.json, diff_report.json, oas.json, raw.json or spec.md in full — they are script-consumed (the visible layer is generated by generate_canvas.py, not hand-drawn from node data). When one specific node's data is needed, window into the file by node id (grep -A/-B or a python one-liner), never a whole-file read. Small files (tokens.json, groups.json, design_classification.json, api_contract.json, component_manifest.json, data_slot_bindings.json, interaction_test_plan.json) may be read whole.
- implementation_plan.json is machine-prefilled (inventory, counts, node coverage, commands, forbidden shortcuts). Your judgment fields: projectAlignment (entrypoint/app shell/feature dirs/fanoutOwnedFiles/faninRequests from READING the current project), fixtureAlignment.fixtureSource + stateData (one shared fixture source; state count is prefilled from the classification and must not shrink), and each region's mergeOrSkipRationale.
- For variant_board designs, plan every state group as runtime data, widget test data, and preview data from one fixture source. A plan with fewer runtime states than the design states is invalid.
- implementation_map.json must map visible render_plan nodes, not just layout regions. Before returning success, run: python3 {scripts_dir / "check_implementation_map.py"} --render-plan {Path(args.spec_dir) / "render_plan.json"} --implementation-map {Path(args.spec_dir) / "implementation_map.json"}
- Each visible-node entry in implementation_map.json must include node, implementation, widget, bbox, and renderMode:"absolute_positioned" (or positioning/layoutMode with the same explicit coordinate meaning). Component ownership without a render-plan bbox mode is invalid.
- Treat render_plan implementation values literally: image/image_png/image_webp/svg/asset nodes are atomic; do not also draw their descendants. image_fill must render the Figma image fill instead of a placeholder. gradient_shape must preserve gradient stops. vector_shape and shape_container must use Figma bbox/fill/border/radius/shadow/effects. clip_group and mask_group must preserve clipping/mask semantics. covered_by_asset, covered_by_text and covered_by_shared_component nodes are not visible widgets. text nodes must render the exact text string from scene/render data, not black boxes. oval_shape nodes must render as ovals, not rectangular bbox fills.
- For screenshot fidelity, the visible layer must be an absolute render-plan canvas: scale the artboard to runtime viewport units, place every visible node at its render_plan bbox with Positioned/CustomPaint/Image/Text equivalents, and preserve design x/y/width/height. Do not rebuild visible card/support/tab regions with Row/Column/Flex spacing or semantic component templates. Semantic widgets are allowed only as transparent hit areas or behavior adapters over the coordinate-rendered pixels.
- If the row asks for paths that do not exist in the current project, do not pretend they exist. Plan the smallest project-consistent scaffold and list shared-file edits for serial fan-in.
- If an artifact schema differs from SKILL.md wording, follow the actual artifact schema and record the mismatch in implementation_plan.json instead of guessing fields.

{shared_section}
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
