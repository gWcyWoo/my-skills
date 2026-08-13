#!/usr/bin/env python3
"""Create the exact prompt used to spawn one iFF worker."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import secrets
import shlex
import time
from urllib.parse import urlsplit


ASSEMBLY_PROMPT_MAX_BYTES = 18_000


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
    parser.add_argument("--component-json", help="One generated shared-component job JSON.")
    parser.add_argument("--spec-dir", required=True,
                        help="board mode: the ONE board dir; fetch/assembly mode: the feature spec root")
    parser.add_argument("--mode", choices=["assembly", "board", "fetch", "contract", "shared"], default="assembly",
                        help="board-level fan-out roles: fetch = run pipeline steps 0-3 scripts per board; "
                             "board = compile ONE board's visual unit (canvas/expected/slots/implementation-map); "
                             "contract = compile ONE feature's step-6 interaction contracts (parallel with board workers); "
                             "assembly = per-feature integration, TDD, device window, audits (consumes contract outputs)")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--recovery-mode",
        choices=["strict-tdd", "preexisting-green"],
        default="strict-tdd",
    )
    args = parser.parse_args()

    skill_dir = Path(args.skill_dir).expanduser().resolve()
    skill_md = skill_dir / "SKILL.md"
    test_rules = skill_dir / "test_rules.md"
    scripts_dir = skill_dir / "scripts"
    required = [
        skill_md,
        test_rules,
        scripts_dir / "verify_pipeline_scripts.py",
    ]
    if args.mode == "assembly":
        required.extend(
            [
                scripts_dir / "assembly_shared_context.py",
                scripts_dir / "assembly_worker_supervisor.py",
            ]
        )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("ERROR: worker prompt inputs missing:\n" + "\n".join(missing))

    row = load_row(args.row_json)
    component = load_row(args.component_json)

    shared_section = ""
    shared_local = Path(args.spec_dir) / "shared_components.local.json"
    assembly_shared_index = None
    assembly_shared_index_path = None
    if args.mode == "assembly":
        from assembly_shared_context import build_index, write_index

        assembly_shared_index_path = (
            Path(args.spec_dir).resolve() / "assembly_shared_components.index.json"
        )
        assembly_shared_index = build_index(Path(args.spec_dir))
        shared_section = f"""
Shared components (bounded READ-ONLY contract):
- Index: {assembly_shared_index_path}
- Before reading or mounting shared components, run: python3 {scripts_dir / "assembly_shared_context.py"} check --index {assembly_shared_index_path}
- The index preserves each local/registry contract path and SHA-256, registration name/widget path, asset/font paths, expected path or JSON-pointer contracts, and per-board reuse mapping/bbox/node-map pointer in deterministic order.
- Use only those indexed paths and pointers. Read verbose expected/node-map bodies on demand; never inline, copy, or return their payload bodies in the prompt or result.
- Mount every indexed reuse registration at its mapped board bbox. Never create, edit, or fork shared component files during assembly; report shared-region visual defects for serial fan-in.
"""
    else:
        components_all = []
        for local_file in (
            [shared_local]
            if shared_local.is_file()
            else sorted(Path(args.spec_dir).glob("*/shared_components.local.json"))
        ):
            shared = json.loads(local_file.read_text(encoding="utf-8"))
            components_all.extend(shared.get("components") or [])
        if components_all:
            shared_section = f"""
Shared components (pre-resolved by the main session — READ-ONLY reuse):
{json.dumps(components_all, ensure_ascii=False, indent=2)}
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
    spec = (Path(args.component_json).resolve().parent
            if args.mode == "shared" and args.component_json
            else Path(args.spec_dir).resolve())
    additional_loaded_files = (
        [skill_dir / "implementation_rules.md", skill_dir / "evolution" / "case_memory.md"]
        if args.mode == "shared"
        else []
    )
    loaded_file_hash_args = "".join(
        " --expected-loaded-file-sha256 "
        f"{shlex.quote(str(path))} {digest(path)}"
        for path in additional_loaded_files
    )
    compliance_command = (
        f"python3 {shlex.quote(str(scripts_dir / 'check_worker_compliance.py'))} --write "
        f"--manifest {shlex.quote(str(spec / 'worker_compliance.json'))} "
        f"--skill-dir {shlex.quote(str(skill_dir))} "
        f"--expected-skill-md-sha256 {hashes['skill_md_sha256']} "
        f"--expected-test-rules-sha256 {hashes['test_rules_sha256']} "
        "--expected-verify-pipeline-scripts-sha256 "
        f"{hashes['verify_pipeline_scripts_sha256']}"
        f"{loaded_file_hash_args}"
    )
    bootstrap = f"""Your FIRST action MUST be this Bash command (run it NOW), then continue top-to-bottom:
1. Run: python3 {scripts_dir / "verify_pipeline_scripts.py"} --skill-dir {skill_dir}
2. Read {skill_md} completely, then {test_rules}.
3. Run: {compliance_command}
This command is the ONLY allowed way to write {spec / "worker_compliance.json"}; do not manually transcribe or reuse hashes. It recomputes the current hashes and exits nonzero if compliance sources changed after prompt generation. On nonzero exit, STOP and report the drift; do not continue with a stale manifest."""

    if args.mode == "shared":
        if not component:
            raise SystemExit("ERROR: --component-json is required for shared mode")
        source = Path(component["source_spec_dir"]).resolve()
        project = Path(args.project_root).resolve()
        widget_path = project / component["widget_path"]
        colors_path = project / component["colors_path"]
        test_path = project / component["test_path"]
        asset_target = project / component["asset_target"]
        bbox = component["bbox"]
        invocation_id = secrets.token_hex(16)
        result_path = Path(component["result_path"]).resolve()
        compliance_path = (spec / "worker_compliance.json").resolve()
        declared_compliance = component.get("compliance_path")
        if declared_compliance and Path(declared_compliance).resolve() != compliance_path:
            raise SystemExit(
                "ERROR: shared component compliance_path must be <job>/worker_compliance.json"
            )
        prompt = f"""IFF_SHARED_COMPONENT_WORKER v1
You implement ONE missing shared component. EXECUTE by RUNNING TOOLS; no prose, no questions. Sibling shared workers run in parallel.
Invocation: {invocation_id}. This worker is valid only when launched through shared_worker_supervisor.py. Use IFF_SHARED_INVOCATION_ID and IFF_SHARED_PROMPT_SHA256 from the supervised environment in the result.
{bootstrap}
1. Read {skill_dir / "implementation_rules.md"} and {skill_dir / "evolution" / "case_memory.md"}; include both paths in loaded_files in {spec / "worker_compliance.json"}.
2. Run make_figma_layout_contract.py with {source / "scene.json"} and {source / "groups.json"}, writing {spec / "component_layout_contract.json"}.
3. Run make_render_plan.py with --scene {source / "scene.json"} --assets {source / "assets_manifest.json"} --layout {spec / "component_layout_contract.json"} --root-node {component["group_node"]} --out {spec / "component_render_plan.raw.json"}.
4. Run prepare_shared_component_assets.py --job {args.component_json} --render-plan {spec / "component_render_plan.raw.json"} --target {asset_target} --out {spec / "component_render_plan.json"} --manifest-out {spec / "shared_assets.json"}.
5. Run check_render_plan.py {spec / "component_render_plan.json"}; nonzero means the design source has a required visible node without a real paint/asset source. STOP, write no success result, and report the exact gate error.
6. Run make_component_manifest.py with the component render plan and {source / "design_classification.json"}, writing {spec / "component_manifest.json"}.
7. Run generate_canvas.py with --render-plan {spec / "component_render_plan.json"} --classification {source / "design_classification.json"} --component-manifest {spec / "component_manifest.json"} --class-name {component["class_name"]} --artboard-width {bbox[2]} --artboard-height {bbox[3]} --colors-out {colors_path} --colors-import {colors_path.name} --asset-prefix {component["asset_target"]}/ --out {widget_path}; require exit 0 and stdout expectedNodeCount > 0, otherwise report failure and do not write a success result.
8. Run {skill_dir / "scripts" / "generate_shared_component_test.py"} --project-root {project} --widget-path {widget_path} --class-name {component["class_name"]} --out {test_path}; DO NOT run the generated test.
9. Write {result_path} with success=true, invocation_id=$IFF_SHARED_INVOCATION_ID, prompt_sha256=$IFF_SHARED_PROMPT_SHA256, result_path={result_path}, compliance_path={compliance_path}, compliance_sha256=SHA256({compliance_path}), signature, name, widget_path, colors_path, test_path, component_expected={str(widget_path) + ".expected.json"}, assets from {spec / "shared_assets.json"}, assets_incomplete, source_spec_dir.
Allowed writes ONLY: {widget_path}, {colors_path}, {test_path}, {asset_target}, and files under {spec}.
FORBIDDEN: pubspec, routes, DI, registry, any other component or feature file, flutter analyze, flutter test, flutter run, hand-written visible Positioned/layout/styles, full reference/artboard image as a visible layer. A node-bbox PNG emitted by prepare_shared_component_assets.py is allowed only when the render-plan node contains valid localized_reference_region assetProvenance.
Return one compact JSON summary containing result_path, compliance_path, success, and error.

Component job JSON:
{json.dumps(component, ensure_ascii=False, indent=2)}

Project root: {project}
"""
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(prompt, encoding="utf-8")
        supervisor = scripts_dir / "shared_worker_supervisor.py"
        invocation_contract = Path(f"{out}.shared_invocation.json")
        contract = {
            "schemaVersion": 1,
            "kind": "iff_shared_component_invocation",
            "invocationId": invocation_id,
            "generatedAtNs": time.time_ns(),
            "prompt": str(out),
            "promptSha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "projectRoot": str(project),
            "jobRoot": str(spec),
            "result": str(result_path),
            "compliance": str(compliance_path),
            "state": str(spec / "shared_supervisor_state.json"),
            "outputLog": str(spec / "shared_worker.log"),
            "failure": str(spec / "shared_failure.json"),
            "skillDir": str(skill_dir),
            "complianceChecker": str(scripts_dir / "check_worker_compliance.py"),
            "complianceCommand": shlex.split(compliance_command),
            "requiredFileSha256": {
                str(skill_md): hashes["skill_md_sha256"],
                str(test_rules): hashes["test_rules_sha256"],
                str(scripts_dir / "verify_pipeline_scripts.py"): hashes[
                    "verify_pipeline_scripts_sha256"
                ],
                str(scripts_dir / "check_worker_compliance.py"): digest(
                    scripts_dir / "check_worker_compliance.py"
                ),
                **{str(path): digest(path) for path in additional_loaded_files},
            },
            "defaultTotalTimeoutSeconds": 1200,
            "defaultIdleTimeoutSeconds": 300,
            "terminationGraceSeconds": 5,
            "supervisor": str(supervisor),
            "workerExitIsSuccess": False,
            "successCriterion": (
                "supervisor exit 0 plus fresh invocation-bound shared_result.json "
                "and current worker compliance"
            ),
            "runCommandPrefix": [
                "python3",
                str(supervisor),
                "run",
                "--contract",
                str(invocation_contract),
                "--",
            ],
        }
        invocation_contract.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"prompt": str(out), "invocationContract": str(invocation_contract)}))
        return 0

    if args.mode == "fetch":
        design_urls = []
        for token in re.findall(
            r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,=%-]+",
            str(row.get("design_url") or ""),
            flags=re.IGNORECASE,
        ):
            parsed = urlsplit(token)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                design_urls.append(token)
        fetch_argv_lines = "\n".join(
            json.dumps(
                ["python3", str(scripts_dir / "fetch.py"), "--url", url, "--parent-dir", str(spec)],
                ensure_ascii=False,
            )
            for url in design_urls
        )
        prompt = f"""IFF_FETCH_WORKER v2
You fetch + compile design boards for ONE sheet row. EXECUTE by RUNNING TOOLS; no prose, no questions.
{bootstrap}
The exact fetch.py argv arrays for this row are below. They override the generic SKILL.md example; execute each array exactly once without rebuilding it from prose or the current working directory:
{fetch_argv_lines}
Each command creates its board under {spec}/<board-title>/. In that returned board directory, run the remaining pipeline steps 1->0->2->3 EXACTLY as SKILL.md commands:
write.py + download_cover.py -> classify_design.py -> export_figma_scene.py + check_figma_scene.py + export_tokens.py + export_assets_manifest.py -> group_figma_layout.py.
Rules: scripts from {scripts_dir} ONLY; zero model judgment beyond error reporting; NEVER read artifact file contents; one board failing must not stop the others (record its error, continue); do not run step 4+ (render_plan waits for shared-component detection).
Network/approval boundary:
- Run each network-bearing command once in the current sandbox. On DNS resolution, connection, network-sandbox, or approval failure, DO NOT request or retry sandbox escalation and do not claim or cite authorization that is not visible to the approval reviewer.
- Do not fabricate, skip, or hand-write outputs. Return the exact argv and error unchanged in this board shape:
  {{"board": ..., "ok": false, "error": ..., "external_blocker": {{"kind": "external_network", "owner": "main_session", "operation": "lanhu_fetch", "requires_escalation": true, "command": ["python3", ...], "error": ...}}}}
- external_blocker.command must copy the failed argv above unchanged, including --parent-dir {spec}; never substitute a relative or generic parent directory.
- Continue the other boards once so main receives one complete blocker list. Main deduplicates exact command arrays, requests bounded escalation with justification "allow the iFF workflow to fetch the user-provided Lanhu design", executes only those reported commands, then uses followup_task on this worker to resume the remaining local pipeline from cached outputs. If escalation is denied, remain blocked visibly.
Return a JSON summary: [{{"board": ..., "ok": true|false, "error": ..., "external_blocker": object|null}}] per board.

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
        feature_spec_root = spec.parent
        feature_key = feature_spec_root.name
        canvas_dir = Path("lib") / feature_key / "presentation"
        canvas_out = canvas_dir / "<SOURCE_NAME>_canvas.dart"
        colors_out = canvas_dir / "<SOURCE_NAME>_canvas_colors.dart"
        prompt = f"""IFF_BOARD_WORKER v1
You compile ONE design board's visual unit for feature {feature_key}. EXECUTE by RUNNING TOOLS; no prose, no questions. Sibling board workers run in parallel — touch ONLY this board's files.
Feature output contract (fixed by this prompt generator from feature spec root {feature_spec_root}; do not reinterpret it from project architecture): `FEATURE_KEY={feature_key}`; `CANVAS_DIR={canvas_dir}`; `OUT={canvas_out}`. Every sibling board under this feature spec root MUST use that same `FEATURE_KEY` and `CANVAS_DIR`. Do NOT replace `CANVAS_DIR` with `lib/src/features` or any other architecture directory.
{bootstrap}
Steps for THIS board ({spec}):
1. python3 {scripts_dir / "summarize_spec_artifacts.py"} --spec-dir {spec} ; read ONLY artifact_digest.json (reading discipline: big JSONs are script-consumed; window by node id when a single node is needed).
2. Step 4 commands: make_figma_layout_contract.py, then make_render_plan.py WITH --shared {shared_local} (must exist; a status=missing entry there means the main session failed to resolve shared components — STOP and return failure), then check_design_artifacts.py.
3. Step 6.7 commands: run make_component_manifest.py. Freeze `SOURCE_NAME` before any canvas output path is accessed. Resolve `SOURCE_NAME` only from existing plan/project naming inputs as the snake_case `<state>` stem; if those inputs do not determine it, STOP with a blocker instead of probing a future output. `CLASS_NAME` = PascalCase(`SOURCE_NAME`) + `Canvas` (for example, `first_loan` -> `FirstLoanCanvas`). Keep `OUT={canvas_out}`, then run generate_canvas.py with `--out {canvas_out} --colors-out {colors_out} --colors-import <SOURCE_NAME>_canvas_colors.dart --class-name <CLASS_NAME>` (+ .expected.json/.slots.json). Do NOT read, grep, rg, cat, stat, or test existence of `OUT` before generate_canvas.py exits 0. Only after generate_canvas.py exits 0 may you read or grep `OUT`. The colors output is owned by this canvas and may be absent when no color tokens are used. copy_assets.py for this board's assets (FILES only — pubspec/fonts registration belongs to assembly).
4. python3 {scripts_dir / "merge_shared_expected.py"} --expected <canvas>.dart.expected.json --local {shared_local} --scene {spec / "scene.json"} --out {spec / "merged_expected.json"}
5. Do NOT inspect `<OUT>.expected.json` with jq or ad-hoc schema fallbacks such as `.nodes[0]`, `.expected[0]`, or `.[0]`. The expected artifact is not an implementation-map input. Run exactly: python3 {scripts_dir / "make_implementation_map.py"} --render-plan {spec / "render_plan.json"} --canvas <OUT> --out {spec / "implementation_map.json"}. This deterministic producer reads the render-plan object and generated canvas directly. If make_implementation_map.py rejects an unsupported schema, STOP and report its error; do not guess another JSON shape. Then run: python3 {scripts_dir / "check_implementation_map.py"} --render-plan {spec / "render_plan.json"} --implementation-map {spec / "implementation_map.json"}
Allowed writes: {canvas_out}{{,.expected.json,.slots.json}}, {colors_out}, assets file copies, everything under {spec}. FORBIDDEN: every canvas directory other than `{canvas_dir}`; page/selector/fixture/slot-mapper or any feature-shared dart, shared or other-board colors files, routes/DI/pubspec/l10n, trace tests, ANY `flutter test`/`flutter run` (the assembly worker owns all test invocations), any other board's files.
Return: {{"board": ..., "canvas": ..., "colors": <path|null>, "expected": ..., "slots": ..., "mergedExpected": ..., "assets": [...], "ok": true|false}}.

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

    if args.mode == "contract":
        row_contract = spec / "row.json"
        row_contract.write_text(
            json.dumps(row, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        prompt = f"""IFF_CONTRACT_WORKER v1
You compile ONE feature's interaction contracts (pipeline step 6 series) for one claimed row. EXECUTE by RUNNING TOOLS; no prose, no questions. You run in parallel with this feature's board workers and MUST NOT touch their files.
{bootstrap}
Steps for feature spec root {spec} (SKILL.md step 6, EXACT commands):
1. Write the row's interaction text to {spec / "interaction.txt"}, then run EXACTLY:
   python3 {scripts_dir / "parse_interactions.py"} --input {spec / "interaction.txt"} --out {spec / "interaction_contract.json"}
   python3 {scripts_dir / "promote_interaction_rules.py"} --contract {spec / "interaction_contract.json"} --completeness-report {spec / "interaction_completeness_report.json"} --out {spec / "interaction_promotion_report.json"}
   This executable command owns the initial completeness run and exactly ONE bounded promotion pass in report order. For every reported occurrence, remove exactly one matching ignoredItems occurrence; append sequential INT-xxx rules with semantic trigger/expectation and matching coverageRequired/testCaseIdsRequired; record duplicate/overlapping occurrences explicitly. Do not renumber or reorder existing rules. It never auto-acknowledges behavior. Genuine non-rules may use acknowledgedNonRules only when their exact whitespace-normalized occurrence matches; overlapping text is not an acknowledgement match.
2. make_state_machine.py (deterministic skeleton) -> YOU fill nodes[*].meaning and every edge's trigger/condition (from interaction text + board semantics + case memory; each edge appended as an INT-SM-xxx rule in interaction_contract.json) -> make_state_machine.py --check must pass.
3. Generate anchors with this EXACT command (all flags are required):
   python3 {scripts_dir / "resolve_interaction_anchors.py"} --contract {spec / "interaction_contract.json"} --index {Path(args.project_root).resolve() / ".iff" / "board_index.json"} --out {spec / "interaction_anchors.json"}
   YOU confirm ambiguous anchors within the listed candidates only and mark zero-hit references pending_route (cross-row targets; tests assert navigation intent against mocks), then validate with this EXACT command:
   python3 {scripts_dir / "resolve_interaction_anchors.py"} --contract {spec / "interaction_contract.json"} --index {Path(args.project_root).resolve() / ".iff" / "board_index.json"} --out {spec / "interaction_anchors.json"} --check
   A nonzero exit stops the worker as failed; do not report success.
4. Verify the OAS closure prepared by main with this EXACT command (do not rename flags or omit --out):
   python3 {scripts_dir / "oas_ref_resource_cache.py"} missing --oas {spec / "oas.json"} --ref-resources {spec / "oas_ref_resources.json"} --out {spec / "oas_missing_ref_paths.json"}
   The output must be `[]` because main owns the missing -> MCP -> merge loop in SKILL.md step 2.5. If it is non-empty, stop and return that path to main; do not call MCP, merge, hand-edit JSON, invent `--cache`, or continue normalization. When it is empty, run:
   python3 {scripts_dir / "normalize_api_contract.py"} --oas {spec / "oas.json"} --ref-resources {spec / "oas_ref_resources.json"} --out {spec / "api_contract.json"}
   This is the full project contract and MUST retain every normalized OAS operation. Read the row api and {spec / "interaction_contract.json"} before selecting anything. The project OAS summary is never feature endpoint evidence; use the full contract only to look up real path+method pairs after the row api or a cited interaction rule explicitly requires an API operation. Your ONLY API judgment is to write {spec / "api_endpoint_selection.json"} with this exact shape: `{{"contractScope":"feature-selection","apiRequired":true|false,"basis":{{"rowApi":"<exact row api>","interactionRuleIds":["INT-..."]}},"selectedEndpoints":[{{"path":"/real/oas/path","method":"GET"}}]}}`. Every non-empty selection MUST be justified by the exact non-empty row api or by a cited interaction rule that explicitly requires that operation; never infer endpoints from OAS names or summaries, screen content, or general project context. If both evidence sources are empty (the row api is empty and interaction_contract.json has no rules), write exactly `{{"contractScope":"feature-selection","apiRequired":false,"basis":{{"rowApi":"","interactionRuleIds":[]}},"selectedEndpoints":[]}}`. That explicit no-API selection is valid and MUST produce a feature contract with `endpointCount=0`, `operationCount=0`, and `selectedEndpoints=[]`; downstream API integration and done gates must then prove that no API is required. Any non-empty selection without row-api or cited interaction-rule evidence MUST stop as invalid. Never delete endpoints from the project contract, invent endpoints, or add fake business calls. Then validate and emit the immutable feature subset with this EXACT command:
   python3 {scripts_dir / "scope_api_contract.py"} --project-contract {spec / "api_contract.json"} --row-json {row_contract} --interaction-contract {spec / "interaction_contract.json"} --selection {spec / "api_endpoint_selection.json"} --out {spec / "feature_api_contract.json"}
   Missing/unknown selections, apiRequired with an empty subset, a non-empty row api marked not required, a non-empty inferred selection without row-api or interaction-rule evidence, or any unscoped contract MUST stop the worker. The explicit `apiRequired=false` zero-operation selection above is the only empty-evidence success path.
   Regenerate the plan with: python3 {scripts_dir / "make_interaction_tests_plan.py"} --contract {spec / "interaction_contract.json"} --api-contract {spec / "feature_api_contract.json"} --out {spec / "interaction_test_plan.json"}
   Then rerun the completeness command exactly once: python3 {scripts_dir / "check_interaction_completeness.py"} --contract {spec / "interaction_contract.json"} --row {spec / "row.json"} --out {spec / "interaction_completeness_report.json"}
   If that single rerun fails, stop visibly with the remaining suspectedMissedRules. Do not acknowledge behavior or iterate again.
5. FINAL HARD GATE (must be the last command before returning success):
   python3 {scripts_dir / "check_contract_artifacts.py"} --spec-dir {spec} --index {Path(args.project_root).resolve() / ".iff" / "board_index.json"}
   Return ok=true only when this command exits 0. Any nonzero exit means ok=false and the contract worker failed.
Reading discipline: read case memory (injected in project AGENTS.md) BEFORE anchor/edge/API judgments and record hit CASE-ids; interaction_contract.json/api_contract.json/small files may be read whole; NEVER read oas.json, oas_ref_resources.json, scene.json, render_plan.json or raw.json in full.
Allowed writes: ONLY feature-level contract artifacts under {spec} (interaction.txt, interaction_contract.json, interaction_completeness_report.json, interaction_promotion_report.json, state_machine.json, interaction_anchors.json, oas_missing_ref_paths.json, api_contract.json, api_endpoint_selection.json, feature_api_contract.json, interaction_test_plan.json). FORBIDDEN: any lib/ or test/ file, any board dir's canvas/expected/slots, pubspec/routes/DI, ANY `flutter` command.
Return: {{"contract": ..., "testPlan": ..., "stateMachine": ..., "anchors": ..., "pendingRoutes": [...], "hitCaseIds": [...], "ok": true|false}}.

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

    out = Path(args.out).resolve()
    project_root = Path(args.project_root).resolve()
    invocation_contract = Path(f"{out}.assembly_invocation.json")
    supervisor = scripts_dir / "assembly_worker_supervisor.py"
    supervisor_state = spec / "assembly_supervisor_state.json"
    board_spec_dirs = sorted(path.resolve() for path in spec.iterdir() if path.is_dir())
    if not board_spec_dirs:
        raise SystemExit(f"ERROR: assembly spec root has no child board directories: {spec}")
    assembly_context = spec / "assembly_context.json"
    assembly_decisions = spec / "assembly_decisions.json"
    batch_plan_script = scripts_dir / "assembly_plan_batch.py"
    prepare_assembly_plans = (
        f"python3 {shlex.quote(str(batch_plan_script))} prepare "
        f"--spec-root {shlex.quote(str(spec))} "
        f"--project-root {shlex.quote(str(Path(args.project_root).resolve()))} "
        f"--context {shlex.quote(str(assembly_context))} "
        f"--decisions {shlex.quote(str(assembly_decisions))}"
    )
    apply_assembly_plans = (
        f"python3 {shlex.quote(str(batch_plan_script))} apply "
        f"--context {shlex.quote(str(assembly_context))} "
        f"--decisions {shlex.quote(str(assembly_decisions))}"
    )
    completion_evidence = spec / "assembly_completion.json"
    issue_completion = (
        f"python3 {shlex.quote(str(scripts_dir / 'assembly_completion.py'))} issue "
        f"--spec-root {shlex.quote(str(spec))} "
        f"--evidence {shlex.quote(str(completion_evidence))}"
    )
    packaging_evidence = spec / "assembly_packaging.json"
    prepare_assembly_packaging = (
        f"python3 {shlex.quote(str(scripts_dir / 'prepare_assembly_packaging.py'))} prepare "
        f"--spec-root {shlex.quote(str(spec))} "
        f"--project-root {shlex.quote(str(project_root))} "
        f"--pubspec {shlex.quote(str(project_root / 'pubspec.yaml'))} "
        f"--out {shlex.quote(str(packaging_evidence))}"
    )
    feature_key = spec.name
    test_target = f"test/{feature_key}"
    guarded_red = (
        f"python3 {shlex.quote(str(scripts_dir / 'assembly_tdd_guard.py'))} red "
        f"--spec-root {shlex.quote(str(spec))} "
        f"--project-root {shlex.quote(str(project_root))} "
        f"--test-target {shlex.quote(test_target)} "
        "--failure-kind missing_feature_behavior"
    )
    guarded_adoption = (
        f"python3 {shlex.quote(str(scripts_dir / 'assembly_tdd_guard.py'))} adopt "
        f"--spec-root {shlex.quote(str(spec))} "
        f"--project-root {shlex.quote(str(project_root))} "
        f"--test-target {shlex.quote(test_target)} "
        "--authorization preexisting-green"
    )
    pre_green_command = (
        guarded_red if args.recovery_mode == "strict-tdd" else guarded_adoption
    )
    guarded_green = (
        f"python3 {shlex.quote(str(scripts_dir / 'assembly_tdd_guard.py'))} green "
        f"--spec-root {shlex.quote(str(spec))} "
        f"--project-root {shlex.quote(str(project_root))} "
        f"--test-target {shlex.quote(test_target)}"
    )
    if args.recovery_mode == "strict-tdd":
        pre_green_instruction = (
            f"Run exactly this guarded RED command:\n```bash\n{pre_green_command}\n```\nDo not invoke "
            "`flutter test` directly and do not write interaction_test_evidence.json by hand. "
            "The guard must observe a nonzero missing-feature/behavior failure; any other "
            "failure STOPS before packaging."
        )
        pre_green_label = "guarded RED"
    else:
        pre_green_instruction = (
            f"The user explicitly authorized preexisting GREEN adoption. Run exactly this "
            f"guarded adoption command:\n```bash\n{pre_green_command}\n```\nDo not create a fake RED, do "
            "not invoke `flutter test` directly, and do not write interaction_test_evidence.json "
            "by hand. The guard must observe exit 0 and hash-lock the existing feature source, "
            "tests, and contracts; any failure STOPS before packaging."
        )
        pre_green_label = "authorized preexisting GREEN adoption"
    fixture_symbol = "".join(
        part[:1].upper() + part[1:]
        for part in feature_key.replace("-", "_").split("_")
        if part
    ) + "VisualFixture"
    runtime_fixture_target = (
        project_root / "lib" / feature_key / "presentation" / f"{feature_key}_page.dart"
    )
    runtime_fixture_pre_gate = (
        f"rg -n -w -F -e {shlex.quote(fixture_symbol)} "
        f"{shlex.quote(str(runtime_fixture_target))}"
    )

    prompt = f"""IFF_WORKER_BOOTSTRAP v1
You are one iFF worker for one claimed row. EXECUTE this pipeline by RUNNING TOOLS; no prose,
questions, or plan-only reply. Stop only after the done-audit result or a concrete blocker.
Process exit is not success: only assembly_worker_supervisor.py verify for {invocation_contract}
may accept this run. Do not rely on automatic skill loading or revert concurrent edits.

Your FIRST action MUST be this Bash command (run it NOW), then continue top-to-bottom:
1. Run: python3 {scripts_dir / "verify_pipeline_scripts.py"} --skill-dir {skill_dir}
2. Do NOT read {skill_md} or {test_rules} in full. This generated prompt is the bounded,
   version-pinned assembly contract. Read only the named compact artifacts and project files below.
3. Keep the skill/test-rule hashes pinned by the generated compliance command; do not expand them
   into the assembly context.
4. Run: {compliance_command}
Only this command may write {spec / "worker_compliance.json"}; it recomputes current hashes. Nonzero means drift: STOP without a stale manifest.

Hard gates:
- ASSEMBLY consumes board artifacts; never regenerate/edit canvases. Run the contract gate command above before writes. DTO/API input is only {spec / "feature_api_contract.json"}; {spec / "api_contract.json"} is provenance. Audit with `python3 {scripts_dir / "check_api_integration.py"} --api-contract {spec / "feature_api_contract.json"} --lib-root lib --out {spec / "api_integration_report.json"}`. Main owns whole-repo regression.
- After RED→GREEN, device evidence, and all audits/reports, run FINAL `{issue_completion}`. Success requires its fresh {completion_evidence}; prose/worker exit 0 is insufficient.
- Use only scripts under {scripts_dir} for deterministic artifacts.
- Compile interaction into contract/test plan and prove coverage with red/green evidence.
- Never use the full design reference as a widget background or visible layer.
- Before selecting a device, run `python3 {scripts_dir / "check_capture_readiness.py"} --project-root {Path(args.project_root).resolve()} --entry {Path(args.project_root).resolve() / "lib" / "main.dart"} --out {spec / "capture_readiness.json"}`; nonzero STOPS before device I/O or repair budget.
- Device gate: run `python3 {scripts_dir / "select_runtime_device.py"} --platform auto --out {spec / "runtime_device.json"}`; commands are bounded and Android falls back to iOS. Never use `adb wait-for-device` or unbounded device commands.
- Build outside the device lock; lock install/launch/capture only. Run `capture_runtime_screenshot.py --selection runtime_device.json --reference <selected-board>/reference.png`. The capture script must accept only consecutive stable frames and reject reference-aware large black-block corruption; never replace actual.png or start diff after that readiness gate fails. If the Android debug APK cannot fit: record ABI; unlock; run `flutter build apk --release --split-per-abi` once; choose its matching release APK; relock; pass it with `--android-apk`; capture once. Never repeat ineffective cleanup/build/install.
- A missing or empty runtime layout trace is a pre-repair blocker, not a repair attempt. Never consume repair budget when `hasActualTrace=false`.
- The feature root owns feature contracts/evidence and is never a board audit target. The batch prepare command audits/prefills every child board in stable order; any failure stops assembly.
- Return only compact evidence and integration paths; never paste plan/digest contents.

Planning gate:
- Run: {prepare_assembly_plans}
- Read {assembly_context} and the current project entrypoint/architecture only far enough to choose project-local names and ownership boundaries. The context lists compact digest paths; open a child digest only when one of the remaining judgments needs it. NEVER read scene.json, render_plan.json, layout_contract.json, implementation_plan.json, repair_plan.json, diff_report.json, oas.json, oas_ref_resources.json, raw.json or spec.md in full.
- Edit ONLY the compact assembly_decisions.json at {assembly_decisions}: fill projectAlignment once for the feature, fixtureSource once, and stateDataByBoard once per board. Do not patch any implementation_plan.json. Region merge/skip rationale and all counts/inventories are deterministic and are applied by the batch script.
- Run: {apply_assembly_plans}
- The apply command is the only allowed implementation-plan writer during assembly. It copies the compact judgments into every machine-prefilled plan and runs check_implementation_plan.py for each board; nonzero stops assembly.
- For variant_board designs, plan every state group as runtime data, widget test data, and preview data from one fixture source. A plan with fewer runtime states than the design states is invalid.
- Every child-board implementation_map.json must map its visible render_plan nodes, not just layout regions; the exact per-board checks already appear in the hard-gate command list above.
- Each visible-node entry in implementation_map.json must include node, implementation, widget, bbox, and renderMode:"absolute_positioned" (or positioning/layoutMode with the same explicit coordinate meaning). Component ownership without a render-plan bbox mode is invalid.
- Obey render_plan literally: asset nodes are atomic; preserve image fills, gradients, vector/shape styles, clips, and masks; covered nodes are not widgets; render exact text and true ovals.
- For screenshot fidelity, compile the Figma 375 logical artboard once: a 750px @2x export becomes logical values by dividing by 2. Never derive a runtime scale from screen width/height and never wrap the page in Transform.scale. At width 375, preserve every logical x/y/width/height/font value. At other widths, adapt only through deterministic left/right/center/stretch constraints, SafeArea, scrolling, and explicit breakpoint reflow where constraints require it; fixed dimensions and font sizes stay unchanged. Semantic widgets may remain transparent hit areas or behavior adapters over the constrained visible layer.
- Apply the image resource contract before coding: prefer pure SVG/VectorDrawable for icons, simple logos, and vectorizable illustrations; treat SVG containing embedded images as a bitmap. Every image needs an explicit logical container size or aspect ratio plus explicit ContentScale/BoxFit, and original pixel dimensions must never drive layout. Android native network photos must use Coil with an ImageRequest sized to logical container x device density, CDN/server resize parameters, explicit contentScale, and memory/disk caching. Flutter local bitmaps need density variants or >=3x source plus decode cacheWidth/cacheHeight from container x devicePixelRatio; network photos need a cached provider, target decode size, and BoxFit. Run {scripts_dir / "check_asset_resources.py"} for every board manifest before GREEN.
- Asset-shape fidelity is `pixelMismatchRealDefect`: visual_diff.py subtracts independently rendered descendant bboxes from a parent asset region and removes cross-engine antialiasing before check_render_fidelity.py gates it. Never raise the tolerance to hide descendant text or AA; real missing, recolored, shifted, or wrong assets must still fail.
- For every dynamic slot, confirm data provenance in data_slot_bindings.json. A value may differ from the design fixture only when confirmedByModel=true, contentSource.kind="api", binding.field is non-empty, and contentSource.evidence names the endpoint/response field or repository field. Pass that file to visual_diff.py and check_render_fidelity.py. API content is exempt from exact text/pixel equality only; its keyed container bbox, constraints, overflow/max-lines behavior, style, resources, interaction, and data wiring remain mandatory. Unconfirmed, local, or static content still requires exact design text.
- If the row asks for paths that do not exist in the current project, do not pretend they exist. Plan the smallest project-consistent scaffold and list shared-file edits for serial fan-in.
- If an artifact schema differs from this generated contract, follow the actual artifact schema and report the mismatch in the compact result summary; never patch implementation_plan.json directly or guess fields.

Assembly fixture/TDD phase (hard order; the same-source check is a post-wiring audit):
1. Create the one shared visual fixture from all generated board slot files. Its generated symbol is `FIXTURE_SYMBOL={fixture_symbol}`.
2. Reference that fixture from the feature tests with the exact `{fixture_symbol}` symbol. {pre_green_instruction}
3. Only after {pre_green_label} evidence is verified, run exactly this deterministic packaging gate:\n{prepare_assembly_packaging}\nIt scans every generated board canvas under this feature, requires every referenced copied asset file, registers every collected asset directory, packages/registers every required mapped font, and writes hash-locked `{packaging_evidence}`. Nonzero STOPS before GREEN. This packaging command must not run flutter test and does not consume any test-call budget. Do not hand-edit pubspec or defer feature packaging to main fan-in.
4. Reference that same fixture from a runtime/page path before GREEN. The required allowed assembly write is `RUNTIME_FIXTURE_TARGET={runtime_fixture_target}`; it must contain the exact generated fixture symbol `{fixture_symbol}` in executable Dart runtime/page code. Import the generated fixture file there and use the symbol directly. Indirect value copies, test-only references, or only a repository abstraction do NOT satisfy this runtime reference contract.
5. Run this executable pre-gate before GREEN:\n{runtime_fixture_pre_gate}\nRequire exit 0 and at least one hit. If the pre-gate exit is nonzero, STOP before GREEN and wire the exact symbol into `RUNTIME_FIXTURE_TARGET`; do not run the strict gate yet.
6. Before GREEN, generate every child board's online-page trace test with {scripts_dir / "gen_layout_trace_test.py"}; pass that child board's `merged_expected.json` to `--expected` (the generator also adapts a raw canvas sidecar by adopting the adjacent merged expectation), each `--trace-out` must be that board's `actual_layout_trace.json`, and the test must exercise the runtime page with the same fixture. The emitted trace must bind `expectedNodeIds` exactly to the canonical expected artifact. The same generated test must exercise at least three logical target viewports (project `.iff/target_viewports.json` via `--viewports-file` when present, otherwise compact/baseline/wide phone defaults), write `responsive_layout_contract.json` + `responsive_layout_report.json`, and pass {scripts_dir / "check_responsive_layout.py"}. The report must use policy `logical_375_constraints`, logicalDesignWidth=375, runtimeScaleAllowed=false, and runtimeScale=1 for every case; fit-width scaling and per-device coordinate forks are forbidden.
7. Only after packaging evidence exists and the runtime pre-gate exits 0, run the required GREEN command:\n{guarded_green}\nNever run `flutter test` directly or hand-write GREEN evidence. The guard rejects stale/out-of-order packaging before `flutter test {test_target}` and requires every step-6 trace to use canonical `{{"pageType": "<runtime page>", "nodes": {{"<node id>": {{...}}}}}}` with non-empty `nodes`; missing/empty/legacy traces STOP before capture without consuming repair budget.
8. Only after {pre_green_label}, packaging, runtime pre-gate, and GREEN succeed, run the unchanged strict same-source gate: python3 {scripts_dir / "check_fixture_source.py"} --root {project_root} --fixture-name {fixture_symbol}
If the strict checker reports `runtime_refs=[]`, runtime wiring is incomplete: return to step 3 before rerunning the unchanged strict gate. Do not treat that state as a terminal checker defect, and do not weaken or bypass the checker.

Assembly visual-repair phase (hard order; at most 32 claims and 3 per source-bound fingerprint):
1. Capture once; generate scoped diff/plan with `--actual-trace <board>/actual_layout_trace.json --require-actual-trace --repair-budget-state {spec / "visual_repair_budget.json"} --top-out {spec / "repair_plan_top.json"}`. The planner excludes consumed fingerprints; nonzero/`hasActualTrace=false` STOPS.
2. STOP before claim/edit if v2 eligibility is false or topAction is null. Initial claim: `python3 {scripts_dir / "visual_repair_budget.py"} claim --state {spec / "visual_repair_budget.json"} --board <selected-board-dir-name> --diff-report <selected-board>/diff_report.json --repair-plan {spec / "repair_plan.json"} --prior-post-repair-diff {spec / "post_repair_diff_report.json"}`.
3. On exit 0, the model reads ONLY {spec / "repair_plan_top.json"}; apply its source-backed action once. Scripts measure/gate and never auto-edit UI.
4. Rebuild/audit/recapture/re-diff; regenerate with the same budget state. Pass stops repair.
5. If still failing with a source-backed fingerprint/topAction, claim with `--fresh-post-diff <selected-board>/diff_report.json`, apply once, return to step 4. If a verified generic planner correction makes the current claimed fingerprint ineligible, run `visual_repair_budget.py replan` with the unchanged scoped diff/current plan to replace that claim and record `plannerInvalidations`; never edit/reset the state JSON. A fourth claim for one fingerprint, threshold change, missing binding, unchanged diff, or claim 33 FAILS. No eligible action while failing STOPS.

{shared_section}
Row JSON:
{json.dumps(row, ensure_ascii=False, indent=2)}

Project root: {Path(args.project_root).resolve()}
Spec dir: {Path(args.spec_dir).resolve()}
"""
    prompt_size = len(prompt.encode("utf-8"))
    if prompt_size > ASSEMBLY_PROMPT_MAX_BYTES:
        raise SystemExit(
            "ERROR: assembly prompt exceeds bounded-context limit: "
            f"{prompt_size} > {ASSEMBLY_PROMPT_MAX_BYTES} bytes"
        )
    write_index(assembly_shared_index, assembly_shared_index_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(prompt, encoding="utf-8")
    contract = {
        "schemaVersion": 2,
        "kind": "iff_assembly_invocation",
        "sessionMode": "fresh_only",
        "resumeAllowed": False,
        "recoveryMode": args.recovery_mode,
        "prompt": str(out),
        "promptSha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "specRoot": str(spec),
        "projectRoot": str(project_root),
        "evidence": str(completion_evidence),
        "state": str(supervisor_state),
        "completionVerifier": str(scripts_dir / "assembly_completion.py"),
        "supervisor": str(supervisor),
        "workerExitIsSuccess": False,
        "successCriterion": "assembly_worker_supervisor.py verify exit 0 for fresh evidence",
        "prepareCommand": [
            "python3", str(supervisor), "prepare", "--contract", str(invocation_contract),
        ],
        "verifyCommand": [
            "python3", str(supervisor), "verify", "--contract", str(invocation_contract),
        ],
        "runCommandPrefix": [
            "python3", str(supervisor), "run", "--contract", str(invocation_contract), "--",
        ],
    }
    invocation_contract.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"prompt": str(out), "invocationContract": str(invocation_contract)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
