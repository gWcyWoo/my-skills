#!/usr/bin/env python3
"""Create the exact prompt used to spawn one iFF worker."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from model_context_contract import expected_workers, persist_model_input, render_contract
from verify_pipeline_scripts import build_report as build_preflight_report


def digest(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_row(path: str | None) -> dict:
    if not path:
        return {}
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def write_prompt(prompt: str, out_value: str, max_bytes: int) -> None:
    encoded = prompt.encode("utf-8")
    if len(encoded) > max_bytes:
        raise SystemExit(
            f"ERROR: worker prompt exceeds {max_bytes} bytes: {len(encoded)}"
        )
    out = Path(out_value)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(encoded)
    print(str(out))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--row-json", help="One claimed CSV/Excel row serialized as JSON.")
    parser.add_argument("--spec-dir", required=True,
                        help="board mode: the ONE board dir; fetch/assembly mode: the feature spec root")
    parser.add_argument("--mode", choices=["assembly", "board"], required=True)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--feature-manifest", required=True)
    parser.add_argument("--preflight-report", required=True)
    parser.add_argument("--max-bytes", type=int, default=8192)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    skill_dir = Path(args.skill_dir).expanduser().resolve()
    skill_md = skill_dir / "SKILL.md"
    test_rules = skill_dir / "test_rules.md"
    implementation_rules = skill_dir / "implementation_rules.md"
    scripts_dir = skill_dir / "scripts"
    required = [
        skill_md,
        test_rules,
        implementation_rules,
        scripts_dir / "verify_pipeline_scripts.py",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("ERROR: worker prompt inputs missing:\n" + "\n".join(missing))

    feature_manifest_path = Path(args.feature_manifest).expanduser().resolve()
    preflight_path = Path(args.preflight_report).expanduser().resolve()
    feature_manifest = json.loads(feature_manifest_path.read_text(encoding="utf-8"))
    stored_preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    current_preflight = build_preflight_report(skill_dir)
    if stored_preflight != current_preflight or not stored_preflight.get("ok"):
        raise SystemExit("ERROR: preflight report is stale or failed")

    spec = Path(args.spec_dir).expanduser().resolve()
    feature_root = spec if args.mode == "assembly" else spec.parent
    workers = expected_workers(feature_manifest)
    if args.mode == "assembly":
        worker = next(item for item in workers if item["role"] == "assembly")
    else:
        matches = [
            item
            for item in workers
            if item["role"] == "board" and item["board"] == spec.name
        ]
        if len(matches) != 1:
            raise SystemExit(
                f"ERROR: board spec is not uniquely owned by feature manifest: {spec.name}"
            )
        worker = matches[0]
    workers_dir = feature_root / ".iff" / "workers"
    contract_input_path = workers_dir / f"{worker['id']}.contract.json"
    receipt_path = workers_dir / f"{worker['id']}.receipt.json"
    result_path = workers_dir / f"{worker['id']}.result.json"

    row = load_row(args.row_json)
    row_path = Path(args.row_json).resolve() if args.row_json else None
    row_reference = (
        f"Row input (script-consumed; do not read in board mode): "
        f"{row_path} sha256={digest(row_path)}"
        if row_path is not None
        else "Row input: none"
    )

    shared_section = ""
    shared_local = Path(args.spec_dir) / "shared_components.local.json"
    # assembly mode gets the feature spec ROOT: aggregate every board's local file.
    shared_files = (
        [shared_local]
        if shared_local.is_file()
        else sorted(Path(args.spec_dir).glob("*/shared_components.local.json"))
    )
    shared_references = []
    for local_file in shared_files:
        shared = json.loads(local_file.read_text(encoding="utf-8"))
        components = shared.get("components") or []
        statuses: dict[str, int] = {}
        for component in components:
            status = str(component.get("status") or "unknown")
            statuses[status] = statuses.get(status, 0) + 1
        shared_references.append(
            {
                "path": str(local_file.resolve()),
                "sha256": digest(local_file),
                "componentCount": len(components),
                "statusCounts": dict(sorted(statuses.items())),
            }
        )
    if shared_references:
        shared_section = f"""
Shared component registries (script-consumed; do not read or embed full entries):
{json.dumps(shared_references, ensure_ascii=False, separators=(',', ':'))}
- Pass --shared {shared_local} to make_render_plan.py; do not redraw covered subtrees.
- Scripts resolve full entries. Never edit shared components during fan-out; report shared diffs for serial fan-in. Stop on status=missing.
"""

    hashes = {
        "skill_md_sha256": digest(skill_md),
        "test_rules_sha256": digest(test_rules),
        "implementation_rules_sha256": digest(implementation_rules),
        "verify_pipeline_scripts_sha256": digest(scripts_dir / "verify_pipeline_scripts.py"),
    }
    bootstrap = f"""This is a bounded role contract; rule SHA values are provenance, not a claim that every rule is copied here.
Preflight is current and bound by SHA: {preflight_path} sha256={digest(preflight_path)}.
Use only scripts under {scripts_dir}. Fail visibly; never waive a failed command."""

    def finalize(body: str) -> int:
        completion = f"""
COMPLETION
Write {result_path} as JSON with an outputs array containing every file produced by this worker.
Run: python3 {scripts_dir / 'complete_worker.py'} --skill-dir {skill_dir} --feature-manifest {feature_manifest_path} --contract-input {contract_input_path} --result {result_path} --out {receipt_path}
Return only after that command succeeds.
"""
        generation = {
            "mode": args.mode,
            "skillDir": str(skill_dir),
            "rowJson": str(row_path) if row_path else None,
            "specDir": str(spec),
            "projectRoot": str(Path(args.project_root).expanduser().resolve()),
            "featureManifest": str(feature_manifest_path),
            "preflightReport": str(preflight_path),
            "promptPath": str(Path(args.out).expanduser().resolve()),
        }
        contract_input = {
            "version": "IFF_WORKER_CONTRACT v3",
            "worker": worker,
            "paths": {
                "featureRoot": str(feature_root),
                "contractInput": str(contract_input_path),
                "receipt": str(receipt_path),
                "result": str(result_path),
            },
            "generation": generation,
            "fingerprints": {
                **hashes,
                "row_json_sha256": digest(row_path) if row_path else None,
                "feature_manifest_sha256": digest(feature_manifest_path),
                "preflight_report_sha256": digest(preflight_path),
                "renderer_sha256": digest(Path(__file__).resolve()),
                "contract_library_sha256": digest(
                    scripts_dir / "model_context_contract.py"
                ),
            },
            "body": body + completion,
        }
        prompt = render_contract(contract_input)
        if len(prompt) > args.max_bytes:
            raise SystemExit(
                f"ERROR: worker prompt exceeds {args.max_bytes} bytes: {len(prompt)}"
            )
        contract_input_path.parent.mkdir(parents=True, exist_ok=True)
        contract_input_path.write_text(
            json.dumps(contract_input, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(prompt)
        persist_model_input(
            prompt,
            kind="worker_prompt",
            owner=worker["id"],
            ledger=feature_root / ".iff" / "model_context.jsonl",
        )
        print(str(out))
        return 0

    if args.mode == "board":
        shared_local = spec / "shared_components.local.json"
        prompt = f"""IFF_BOARD_WORKER v1
You compile ONE design board's visual unit for feature <feature> (derive from the spec path). EXECUTE by RUNNING TOOLS; no prose, no questions. Sibling board workers run in parallel — touch ONLY this board's files.
{bootstrap}
Steps for THIS board ({spec}):
1. python3 {scripts_dir / "summarize_spec_artifacts.py"} --spec-dir {spec}; then python3 {scripts_dir / "make_visual_model_packet.py"} --spec-dir {spec} --out {spec / "visual_model_packet.json"}; read ONLY visual_model_packet.json (big JSONs are script-consumed; window by node id only when the packet names one).
2. Step 4 commands: make_figma_layout_contract.py, then make_render_plan.py WITH --shared {shared_local} (must exist; a status=missing entry there means the main session failed to resolve shared components — STOP and return failure), then check_design_artifacts.py.
3. Step 6.7 commands: make_component_manifest.py then generate_canvas.py -> lib/<feature>/presentation/<state>_canvas.dart (+ .expected.json/.slots.json). copy_assets.py for this board's assets (FILES only — project-wide registration belongs to main fan-in).
4. python3 {scripts_dir / "merge_shared_expected.py"} --expected <canvas>.dart.expected.json --local {shared_local} --scene {spec / "scene.json"} --out {spec / "merged_expected.json"}
5. Run make_implementation_map.py from render_plan.json + the generated canvas expected JSON, write {spec / "implementation_map.json"}, then run check_implementation_map.py.
Allowed writes: lib/<feature>/presentation/<state>_canvas.dart{{,.expected.json,.slots.json}}, assets file copies, everything under {spec}. FORBIDDEN: page/selector/colors/fixture/slot-mapper or any feature-shared dart, routes/DI/pubspec/l10n, trace tests, ANY `flutter test`/`flutter run` (the assembly worker owns all test invocations), any other board's files.
Return: {{"board": ..., "canvas": ..., "expected": ..., "slots": ..., "mergedExpected": ..., "assets": [...], "ok": true|false}}.

{row_reference}
{shared_section}

Project root: {Path(args.project_root).resolve()}
Spec dir: {spec}
"""
        return finalize(prompt)

    assembly_facts = (
        {"title": row["title"]} if row.get("title") is not None else {}
    )
    row_sources = []
    if row_path is not None:
        for key, filename in (
            ("ui_notes", "row_ui_notes.txt"),
            ("interaction", "row_interaction.txt"),
            ("api", "row_api.txt"),
        ):
            source_path = spec / filename
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text(str(row.get(key) or ""), encoding="utf-8")
            row_sources.append(
                {
                    "kind": key,
                    "path": str(source_path.resolve()),
                    "sha256": digest(source_path),
                }
            )

    prompt = f"""IFF_ASSEMBLY_WORKER v2
Execute tools and edits; no prose/questions. Stop only after all gates or a concrete failure. Preserve concurrent edits.
{bootstrap}
Paths: project={Path(args.project_root).resolve()} spec={Path(args.spec_dir).resolve()} scripts={scripts_dir}

ROLE/OWNERSHIP
- Consume board canvas/expected/slots/merged_expected/implementation_map; never edit canvases.
- Own feature selector/page/colors, fixture, slot mapper, interaction/data integration and tests.
- FORBIDDEN: pubspec, routes/DI, project asset/font registration, target-client run and final gates. Write bounded fan_in_request.json and state_changes.json for main.
- Use only {scripts_dir}; report missing paths/schema conflicts instead of guessing.

BOUNDED MODEL INPUT
- Run summarize_spec_artifacts.py; large inputs stay script-side. Read only each packet's one action and selected node window.
- Visual: make_visual_model_packet.py.
- Interaction judgment: make_interaction_model_packet.py --spec-root {Path(args.spec_dir).resolve()} --project-root {Path(args.project_root).resolve()} --out {Path(args.spec_dir).resolve() / "interaction_model_packet.json"}; read ONLY interaction_model_packet.json, resolve its one action, regenerate.
- Data: merge_feature_data.py for multi-state, then make_data_model_packet.py --spec-root {Path(args.spec_dir).resolve()} --out {Path(args.spec_dir).resolve() / "data_model_packet.json"}; resolve one action. Keep nodes state-qualified; fail stale/conflicting inputs.

QUALITY PIPELINE
1. check_design_artifacts.py defines geometry; never guess or use a reference background.
2. prefill_implementation_plan.py; resolve declared __MODEL__ fields only, then check_implementation_plan.py.
3. Compile/check every interaction rule, slot, repository, binding and state.
4. Strict TDD: run_feature_tests.py once RED and once GREEN; each shared run writes interaction/data evidence with current hashes.
5. Diff, apply at most one repair, re-capture/re-diff once; fail if thresholds miss.
6. One audit run covers all state traces and implementation_map node/widget/bbox/absolute-mode. Keep render nodes atomic and semantic adapters transparent.
7. Main serially applies fan_in_request.json, runs target client and final gates.

Return a bounded summary of plan, RED/GREEN, data and visual evidence plus fan-in requests.
{row_reference}
Assembly facts: {json.dumps(assembly_facts, ensure_ascii=False, separators=(',', ':'))}
Script-only row sources (never read whole in model context): {json.dumps(row_sources, ensure_ascii=False, separators=(',', ':'))}
{shared_section}
"""
    return finalize(prompt)


if __name__ == "__main__":
    raise SystemExit(main())
