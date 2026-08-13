#!/usr/bin/env python3
"""ICP P2d2a/P2d2b/P2d2c Flutter trusted-operation plan registry.

This module is the static trusted-operation plan registry for the
legacy-backed Flutter argv builders:

P2d2a (visible/fixture/trace):

* ``flutter.visible_codegen.v1``
* ``flutter.fixture_codegen.v1``
* ``flutter.trace_harness.v1``

P2d2b (packaging/test_runner, append-only):

* ``flutter.packaging.v1``
* ``flutter.test_runner.v1``

P2d2c (runtime_capture/project_gates/fan_in, append-only):

* ``flutter.runtime_capture.v1``
* ``flutter.project_gates.v1``
* ``flutter.fan_in.v1``

It validates typed requests and returns deterministic argv plans. It
does not execute subprocesses, write outputs, activate the adapter,
modify the P2c descriptor, or implement any remaining operation
builders.

For the P2d2c operations the plan carries no separate ``project_root``
field; ``verify_plan`` reconstructs the action's exact normalized
request from the validated plan's ``(operation_id, step_id)``, ``cwd``,
and validated argv values, canonical-JSON hashes that reconstructed
mapping, and requires exact equality with ``request_digest``. This
couples ``cwd`` to the digest so a cwd-only substitution is detected
even for actions whose argv contains only spec-root paths.

Public Python API (no CLI, no executor):

* ``list_operation_ids() -> tuple[str, ...]``
* ``build(operation_id: str, request: dict) -> dict``
* ``verify_plan(plan: dict) -> dict``

Locked boundaries:

* Stdlib only. No ``subprocess`` import; the module never invokes a
  shell-enabled subprocess.
* Fixed ``sys.executable``, fixed capsule path, fixed script basenames,
  fixed flags, fixed timeouts.
* Each primitive SHA comes from the immutable P2a manifest after capsule
  verification.
* ``build()`` verifies the installed P2a vendored capsule first through
  the fixed verifier, strict-loads the fixed vendor manifest with
  duplicate-key rejection, validates the exact request schema, builds a
  canonical plan, calls ``verify_plan()`` on it, and returns the plan.
* Generic failures expose type only through the module-local typed
  exception :class:`OperationPlanError`; arbitrary exception text is
  never leaked.
* The module never imports, reads, executes, or follows a symlink into
  sibling ``iff/``. It never edits the registry or P2c descriptor, never
  writes to the project/run/capsule trees, and never mutates any file.
* No public root/manifest/capsule/registry/executable override is
  exposed; all production paths are derived from this module's installed
  location.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Public schema constants.
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
KIND_PLAN = "icp.trusted-operation-plan.v1"
KIND_VERIFY = "icp.trusted-operation-plan-verify.v1"
PLATFORM_ID = "flutter"
PROFILE_ID = "flutter-standard"
TIMEOUT_SECONDS = 120
TIMEOUT_TDD_SECONDS = 600
SCRIPT_NAME = "flutter_operations_v1.py"

# Local error code. This is NOT an ICP pre-claim code and does not extend
# icp_common.ALL_ERROR_CODES.
CODE = "trusted_operation_plan_failed"

# ---------------------------------------------------------------------------
# Fixed production paths derived from this module's installed location.
# Accepts NO override; this is the runtime surface.
# ---------------------------------------------------------------------------

ICP_ROOT = Path(__file__).resolve().parents[2]
CAPSULE_SCRIPTS_DIR = ICP_ROOT / "vendor" / "iff_v1" / "scripts"
# Fixed installed platform scripts directory. Platform-origin steps
# (e.g. ``adapt_expected_slots``) resolve ONLY through this directory;
# the basename must not collide with any capsule-manifest primitive, and
# the file must be a regular non-symlink file whose SHA-256 is recomputed
# on every build/verify (no manifest entry is consulted for platform
# primitives). Accepts NO override.
PLATFORM_SCRIPTS_DIR = ICP_ROOT / "scripts" / "platforms"
MANIFEST_PATH = ICP_ROOT / "references" / "baselines" / "iff-v1-vendor.json"
VERIFY_TOOL = ICP_ROOT / "scripts" / "verify_vendor_iff_v1.py"

# ---------------------------------------------------------------------------
# Fixed operation IDs and step specifications.
#
# Each operation's step spec is a tuple of step dicts. Each step dict has:
#   step_id       - the fixed step identifier
#   primitive     - the fixed script basename (e.g. "generate_canvas.py")
#   argv_spec     - tuple of (flag, value_kind, min_count, max_count)
#   script_origin - closed origin field: "capsule" (default) or "platform".
#                   "capsule" resolves through CAPSULE_SCRIPTS_DIR and the
#                   frozen vendor manifest; "platform" resolves through
#                   PLATFORM_SCRIPTS_DIR and a recomputed file SHA-256.
#                   The plan schema carries no caller-controlled origin
#                   field; verification recovers origin from the fixed
#                   (operation_id, step_id) specification.
#
# value_kind is one of:
#   abs_path_json        absolute normalized path ending .json
#   abs_path_dart        absolute normalized path ending .dart
#   abs_path_trace_test  absolute normalized path ending _layout_trace_test.dart
#   dart_class           Dart class identifier ^[A-Z][A-Za-z0-9]*$
#   feature_id           feature/state identifier ^[a-z][a-z0-9_]*$
#   package_import       package:<pkg>/<rel>.dart
#   asset_prefix         assets/icp/<feature_id>
#   safe_area_enum       edge_to_edge | inset_content
#   slots_pair           STATE=ABS.json
#   projection_pair      STATE=ABS.json (P2.5b fixture guard)
# ---------------------------------------------------------------------------

# Closed origin values for the internal step spec's script_origin field.
_ORIGIN_CAPSULE = "capsule"
_ORIGIN_PLATFORM = "platform"
_CLOSED_ORIGINS = frozenset({_ORIGIN_CAPSULE, _ORIGIN_PLATFORM})

# cwd-binding enum (string constants for explicit metadata). Defined
# early so step specs below may reference any cwd_binding value.
_CWD_PROJECT_ROOT_OR_DESCENDANT = "project_root_or_descendant"
_CWD_EVIDENCE_PARENT = "evidence_parent"
_CWD_SPEC_ROOT = "spec_root"
# P2.5b: the fixture projection guard step's cwd is the validated
# project_root, but its argv carries only ``--run-root`` plus
# projection/slots paths under run_root (none of which anchor cwd
# directly when run_root is disjoint from project_root). This rule
# re-attests the cwd<->run_root relationship by extracting the
# ``--run-root`` argv value and re-applying the root-nesting policy
# between cwd (as project_root) and run_root.
_CWD_PROJECT_ROOT_WITH_RUN_ROOT = "project_root_with_run_root"
# P2.5d: trace_harness chain binding. Steps 0 (merge) and 1 (gate) carry
# only run-root-anchored argv paths; their cwd provenance is closed by
# chaining their cwd to the following step's cwd until the chain
# terminates at step 2 (gen_layout_trace_test), whose default
# _CWD_PROJECT_ROOT_OR_DESCENDANT binding independently anchors cwd to
# project_root via its --out argv value.
_CWD_TRACE_HARNESS_CHAIN = "trace_harness_chain"

_OPERATION_IDS: tuple[str, ...] = (
    "flutter.visible_codegen.v1",
    "flutter.fixture_codegen.v1",
    "flutter.trace_harness.v1",
    "flutter.packaging.v1",
    "flutter.test_runner.v1",
    "flutter.runtime_capture.v1",
    "flutter.project_gates.v1",
    "flutter.fan_in.v1",
)

_VISIBLE_STEPS_SPEC: tuple[dict[str, Any], ...] = (
    {
        "step_id": "generate_canvas",
        "primitive": "generate_canvas.py",
        "script_origin": _ORIGIN_CAPSULE,
        "argv_spec": (
            ("--render-plan", "abs_path_json", 1, 1),
            ("--out", "abs_path_dart", 1, 1),
            ("--colors-out", "abs_path_dart", 1, 1),
            ("--colors-import", "package_import", 1, 1),
            ("--asset-prefix", "asset_prefix", 1, 1),
            ("--classification", "abs_path_json", 1, 1),
            ("--component-manifest", "abs_path_json", 1, 1),
            ("--class-name", "dart_class", 1, 1),
        ),
    },
    {
        # P2.5a2/P2.5b: explicit, digest-bound post-step that
        # reconstructs the accepted SharedCore projection from the frozen
        # generate_canvas sidecars, proves byte parity, and atomically
        # persists the byte-identical SharedCore output. P2.5b extends
        # the adapter argv with the validated ``--run-root`` and
        # ``--feature-id`` pair so the adapter additionally publishes the
        # canonical projection artifact under
        # ``<run_root>/expected_slots_projections/<feature_id>.json``.
        # This is a fixed project-local platform primitive; it is never
        # copied into or registered inside the frozen vendor capsule.
        # Its script_origin is "platform", so the script path resolves
        # through PLATFORM_SCRIPTS_DIR and its SHA-256 is recomputed
        # from the regular non-symlink file on every build/verify (no
        # manifest entry is consulted).
        "step_id": "adapt_expected_slots",
        "primitive": "flutter_expected_slots_adapter_v1.py",
        "script_origin": _ORIGIN_PLATFORM,
        "argv_spec": (
            ("--project-root", "abs_path_dir", 1, 1),
            ("--canvas", "abs_path_dart", 1, 1),
            ("--run-root", "abs_path_dir", 1, 1),
            ("--feature-id", "feature_id", 1, 1),
        ),
    },
    {
        "step_id": "make_implementation_map",
        "primitive": "make_implementation_map.py",
        "script_origin": _ORIGIN_CAPSULE,
        "argv_spec": (
            ("--render-plan", "abs_path_json", 1, 1),
            ("--canvas", "abs_path_dart", 1, 1),
            ("--out", "abs_path_json", 1, 1),
        ),
    },
    {
        "step_id": "make_status_bar_policy",
        "primitive": "make_status_bar_policy.py",
        "script_origin": _ORIGIN_CAPSULE,
        "argv_spec": (
            ("--scene", "abs_path_json", 1, 1),
            ("--class-name", "dart_class", 1, 1),
            ("--out", "abs_path_dart", 1, 1),
        ),
    },
)

_FIXTURE_STEPS_SPEC: tuple[dict[str, Any], ...] = (
    {
        # P2.5b: read-only platform-origin projection guard that gates
        # the fixture operation on the canonical platform-neutral
        # expected/slots projection. The guard verifies that for each
        # state, the projection artifact's canonical bytes (via
        # SharedCore build_projection_bytes) equal its on-disk bytes
        # AND that the projection's legacy slots bytes (via SharedCore
        # build_legacy_bytes) equal the slots file bytes. Only after
        # this guard succeeds may the existing frozen
        # make_visual_fixture.py capsule consumer run. The platform
        # basename must not collide with any capsule-manifest primitive
        # and its SHA-256 is recomputed from the regular non-symlink
        # file on every build/verify.
        "step_id": "verify_fixture_projections",
        "primitive": "flutter_fixture_projection_guard_v1.py",
        "script_origin": _ORIGIN_PLATFORM,
        "cwd_binding": _CWD_PROJECT_ROOT_WITH_RUN_ROOT,
        "argv_spec": (
            ("--run-root", "abs_path_dir", 1, 1),
            ("--projection", "projection_pair", 1, None),
            ("--slots", "slots_pair", 1, None),
        ),
    },
    {
        "step_id": "make_visual_fixture",
        "primitive": "make_visual_fixture.py",
        "argv_spec": (
            ("--feature", "feature_id", 1, 1),
            ("--slots", "slots_pair", 1, None),
            ("--out", "abs_path_dart", 1, 1),
        ),
    },
)

_TRACE_STEPS_SPEC: tuple[dict[str, Any], ...] = (
    {
        # P2.5d step 0: frozen capsule merge_shared_expected.py consumes
        # the real legacy page .expected.json plus the optional
        # shared_components.local.json + scene.json, and produces the
        # canonical merged_expected.json. This is the trusted producer
        # of the document the trace consumer will verify against.
        "step_id": "merge_shared_expected",
        "primitive": "merge_shared_expected.py",
        "script_origin": _ORIGIN_CAPSULE,
        "cwd_binding": _CWD_TRACE_HARNESS_CHAIN,
        "argv_spec": (
            ("--expected", "abs_path_json", 1, 1),
            ("--local", "abs_path_json", 1, 1),
            ("--scene", "abs_path_json", 1, 1),
            ("--out", "abs_path_json", 1, 1),
        ),
    },
    {
        # P2.5d step 1: platform-origin gate that proves the P2.5a
        # projection reconstructs the legacy page canvas expected
        # (byte parity), proves the merge output is canonical, attests
        # the actual chain files via the manifest-bound producer SHA,
        # and atomically publishes + re-verifies P2.5c provenance.
        "step_id": "verify_merged_expectation_provenance",
        "primitive": "flutter_merged_expectation_provenance_gate_v1.py",
        "script_origin": _ORIGIN_PLATFORM,
        "cwd_binding": _CWD_TRACE_HARNESS_CHAIN,
        "argv_spec": (
            ("--run-root", "abs_path_dir", 1, 1),
            ("--page-canvas-expected", "abs_path_json", 1, 1),
            ("--page-canvas-projection", "abs_path_json", 1, 1),
            ("--shared-components-local", "abs_path_json", 1, 1),
            ("--scene", "abs_path_json", 1, 1),
            ("--merged-expected", "abs_path_json", 1, 1),
            ("--provenance-out", "abs_path_json", 1, 1),
        ),
    },
    {
        # P2.5d step 2: frozen capsule gen_layout_trace_test.py. Its
        # --expected is bound to the attested merged_expected.json so
        # the consumer's raw-sidecar + adjacent-merged auto-adoption
        # branch is structurally unreachable. The default
        # cwd_binding (_CWD_PROJECT_ROOT_OR_DESCENDANT) anchors cwd to
        # project_root via --out.
        "step_id": "gen_layout_trace_test",
        "primitive": "gen_layout_trace_test.py",
        "argv_spec": (
            ("--expected", "abs_path_json", 1, 1),
            ("--page-import", "package_import", 1, 1),
            ("--page-type", "dart_class", 1, 1),
            ("--trace-out", "abs_path_json", 1, 1),
            ("--responsive-out", "abs_path_json", 1, 1),
            ("--responsive-contract-out", "abs_path_json", 1, 1),
            ("--viewports-file", "abs_path_json", 1, 1),
            ("--safe-area-policy", "safe_area_enum", 1, 1),
            ("--out", "abs_path_trace_test", 1, 1),
        ),
    },
)

# ---------------------------------------------------------------------------
# P2d2b packaging/test_runner step specs.
#
# Each step spec carries:
#   step_id         - the fixed step identifier
#   primitive       - the fixed capsule basename (e.g. "copy_assets.py")
#   argv_spec       - tuple of (flag, value_kind, min_count, max_count)
#   positional      - optional fixed positional subcommand that must
#                     appear at argv[2] before the flag/value pairs, or
#                     None when the primitive does not use subparsers
#   cwd_binding     - explicit cwd-binding rule that verify_plan must
#                     re-prove from the plan itself. One of:
#                       "project_root_or_descendant" - cwd must be the
#                         canonical project_root, and at least one
#                         validated absolute argv path must equal cwd
#                         OR be a strict descendant of cwd. This covers
#                         every P2d2a step and every project-bound P2d2b
#                         step (packaging copy/update/prepare, test_runner
#                         red/green/adopt/retire).
#                       "evidence_parent" - cwd must equal the lexical
#                         parent directory of the validated absolute
#                         ``--evidence`` argv value (packaging verify).
#                       "spec_root" - cwd must equal the validated
#                         absolute ``--spec-root`` argv value
#                         (test_runner verify).
#                     The plan schema carries no separate project_root
#                     field; the cwd value is derived deterministically
#                     from the validated argv path values.
# ---------------------------------------------------------------------------

# cwd-binding enum (string constants for explicit metadata).
# Defined alongside the closed origins above so every step spec can
# reference any cwd_binding value at module load time.
_PACKAGING_COPY_ASSETS_STEP: dict[str, Any] = {
    "step_id": "copy_assets",
    "primitive": "copy_assets.py",
    "positional": None,
    "cwd_binding": _CWD_PROJECT_ROOT_OR_DESCENDANT,
    "argv_spec": (
        ("--manifest", "abs_path_json", 1, 1),
        ("--target", "abs_path_dir", 1, 1),
    ),
}

_PACKAGING_UPDATE_PUBSPEC_ASSET_STEP: dict[str, Any] = {
    "step_id": "update_pubspec_asset",
    "primitive": "update_pubspec_assets.py",
    "positional": None,
    "cwd_binding": _CWD_PROJECT_ROOT_OR_DESCENDANT,
    "argv_spec": (
        ("--pubspec", "abs_path_yaml", 1, 1),
        ("--asset", "rel_asset", 1, 1),
    ),
}

_PACKAGING_PREPARE_STEP: dict[str, Any] = {
    "step_id": "prepare_assembly_packaging",
    "primitive": "prepare_assembly_packaging.py",
    "positional": "prepare",
    "cwd_binding": _CWD_PROJECT_ROOT_OR_DESCENDANT,
    "argv_spec": (
        ("--spec-root", "abs_path_dir", 1, 1),
        ("--project-root", "abs_path_dir", 1, 1),
        ("--pubspec", "abs_path_yaml", 1, 1),
        ("--out", "abs_path_json", 1, 1),
    ),
}

_PACKAGING_VERIFY_STEP: dict[str, Any] = {
    "step_id": "verify_assembly_packaging",
    "primitive": "prepare_assembly_packaging.py",
    "positional": "verify",
    "cwd_binding": _CWD_EVIDENCE_PARENT,
    "argv_spec": (
        ("--evidence", "abs_path_json", 1, 1),
    ),
}

_TEST_RUNNER_RED_STEP: dict[str, Any] = {
    "step_id": "assembly_tdd_red",
    "primitive": "assembly_tdd_guard.py",
    "positional": "red",
    "cwd_binding": _CWD_PROJECT_ROOT_OR_DESCENDANT,
    "argv_spec": (
        ("--spec-root", "abs_path_dir", 1, 1),
        ("--project-root", "abs_path_dir", 1, 1),
        ("--test-target", "rel_test_target", 1, 1),
        ("--failure-kind", "fixed_failure_kind", 1, 1),
    ),
}

_TEST_RUNNER_GREEN_STEP: dict[str, Any] = {
    "step_id": "assembly_tdd_green",
    "primitive": "assembly_tdd_guard.py",
    "positional": "green",
    "cwd_binding": _CWD_PROJECT_ROOT_OR_DESCENDANT,
    "argv_spec": (
        ("--spec-root", "abs_path_dir", 1, 1),
        ("--project-root", "abs_path_dir", 1, 1),
        ("--test-target", "rel_test_target", 1, 1),
    ),
}

_TEST_RUNNER_ADOPT_STEP: dict[str, Any] = {
    "step_id": "assembly_tdd_adopt",
    "primitive": "assembly_tdd_guard.py",
    "positional": "adopt",
    "cwd_binding": _CWD_PROJECT_ROOT_OR_DESCENDANT,
    "argv_spec": (
        ("--spec-root", "abs_path_dir", 1, 1),
        ("--project-root", "abs_path_dir", 1, 1),
        ("--test-target", "rel_test_target", 1, 1),
        ("--authorization", "fixed_authorization", 1, 1),
    ),
}

_TEST_RUNNER_VERIFY_STEP: dict[str, Any] = {
    "step_id": "verify_assembly_tdd",
    "primitive": "assembly_tdd_guard.py",
    "positional": "verify",
    "cwd_binding": _CWD_SPEC_ROOT,
    "argv_spec": (
        ("--spec-root", "abs_path_dir", 1, 1),
    ),
}

_TEST_RUNNER_RETIRE_STEP: dict[str, Any] = {
    "step_id": "retire_stale_template_tests",
    "primitive": "retire_stale_flutter_template_tests.py",
    "positional": None,
    "cwd_binding": _CWD_PROJECT_ROOT_OR_DESCENDANT,
    "argv_spec": (
        ("--project-root", "abs_path_dir", 1, 1),
        ("--out", "abs_path_json", 1, 1),
    ),
}

# ---------------------------------------------------------------------------
# P2d2c runtime_capture/project_gates/fan_in step specs.
#
# Every P2d2c variant is a single-step operation whose cwd is the canonical
# project_root. Unlike P2d2a/P2d2b, the cwd relationship is proven through
# normalized-request digest coupling (see ``_CWD_DIGEST_COUPLING`` and
# ``_verify_p2d2c_normalized_request``) rather than a project-rooted argv
# anchor, because several P2d2c actions (select_device, capture) carry only
# spec-root paths while cwd is project-root.
#
# Each spec carries a fixed ``timeout`` (read by ``verify_plan``) and the
# ``argv_spec`` validates the fixed flag/value structure including fixed
# literal tokens via the ``literal:<value>`` value kind.
# ---------------------------------------------------------------------------

# cwd-binding sentinel: the cwd relationship is proven by the normalized-
# request digest coupling in ``_verify_p2d2c_normalized_request``.
_CWD_DIGEST_COUPLING = "digest_coupling"

# Fixed timeouts for runtime_capture variants.
_TIMEOUT_SELECT_DEVICE = 180
_TIMEOUT_LOCK_ACQUIRE = 960
_TIMEOUT_LOCK_RELEASE = 120
_TIMEOUT_LOCK_STATUS = 120
_TIMEOUT_CAPTURE = 600
_TIMEOUT_PHYSICAL_PREVIEW = 180

_RUNTIME_CAPTURE_SELECT_DEVICE_STEP: dict[str, Any] = {
    "step_id": "select_device",
    "primitive": "select_runtime_device.py",
    "positional": None,
    "cwd_binding": _CWD_DIGEST_COUPLING,
    "timeout": _TIMEOUT_SELECT_DEVICE,
    "argv_spec": (
        ("--platform", "literal:auto", 1, 1),
        ("--command-timeout", "literal:10", 1, 1),
        ("--boot-timeout", "literal:120", 1, 1),
        ("--out", "abs_path_json", 1, 1),
    ),
}

_RUNTIME_CAPTURE_LOCK_ACQUIRE_STEP: dict[str, Any] = {
    "step_id": "lock_acquire",
    "primitive": "device_lock.py",
    "positional": "acquire",
    "cwd_binding": _CWD_DIGEST_COUPLING,
    "timeout": _TIMEOUT_LOCK_ACQUIRE,
    "argv_spec": (
        ("--lock", "abs_path_plain", 1, 1),
        ("--timeout", "literal:900", 1, 1),
    ),
}

_RUNTIME_CAPTURE_LOCK_RELEASE_STEP: dict[str, Any] = {
    "step_id": "lock_release",
    "primitive": "device_lock.py",
    "positional": "release",
    "cwd_binding": _CWD_DIGEST_COUPLING,
    "timeout": _TIMEOUT_LOCK_RELEASE,
    "argv_spec": (
        ("--lock", "abs_path_plain", 1, 1),
    ),
}

_RUNTIME_CAPTURE_LOCK_STATUS_STEP: dict[str, Any] = {
    "step_id": "lock_status",
    "primitive": "device_lock.py",
    "positional": "status",
    "cwd_binding": _CWD_DIGEST_COUPLING,
    "timeout": _TIMEOUT_LOCK_STATUS,
    "argv_spec": (
        ("--lock", "abs_path_plain", 1, 1),
    ),
}

_RUNTIME_CAPTURE_CAPTURE_STEP: dict[str, Any] = {
    "step_id": "capture",
    "primitive": "capture_runtime_screenshot.py",
    "positional": None,
    "cwd_binding": _CWD_DIGEST_COUPLING,
    "timeout": _TIMEOUT_CAPTURE,
    "argv_spec": (
        ("--selection", "abs_path_json", 1, 1),
        ("--command-timeout", "literal:15", 1, 1),
        ("--launch-timeout", "literal:300", 1, 1),
        ("--out", "abs_path_png", 1, 1),
        ("--manifest", "abs_path_json", 1, 1),
    ),
}

_RUNTIME_CAPTURE_PHYSICAL_PREVIEW_STEP: dict[str, Any] = {
    "step_id": "physical_preview",
    "primitive": "physical_device_preview.py",
    "positional": None,
    "cwd_binding": _CWD_DIGEST_COUPLING,
    "timeout": _TIMEOUT_PHYSICAL_PREVIEW,
    "argv_spec": (
        ("--project-root", "abs_path_dir", 1, 1),
        ("--out", "abs_path_json", 1, 1),
    ),
}

_PROJECT_GATES_INTERACTION_WIRING_STEP: dict[str, Any] = {
    "step_id": "interaction_wiring",
    "primitive": "check_interaction_wiring.py",
    "positional": None,
    "cwd_binding": _CWD_DIGEST_COUPLING,
    "timeout": TIMEOUT_SECONDS,
    "argv_spec": (
        ("--lib-root", "abs_path_dir", 1, 1),
        ("--test-root", "abs_path_dir", 1, 1),
        ("--entry", "abs_path_dart", 1, 1),
        ("--pubspec", "abs_path_yaml", 1, 1),
        ("--contract", "abs_path_json", 1, 1),
        ("--out", "abs_path_json", 1, 1),
    ),
}

_PROJECT_GATES_API_INTEGRATION_STEP: dict[str, Any] = {
    "step_id": "api_integration",
    "primitive": "check_api_integration.py",
    "positional": None,
    "cwd_binding": _CWD_DIGEST_COUPLING,
    "timeout": TIMEOUT_SECONDS,
    "argv_spec": (
        ("--api-contract", "abs_path_json", 1, 1),
        ("--lib-root", "abs_path_dir", 1, 1),
        ("--out", "abs_path_json", 1, 1),
    ),
}

_PROJECT_GATES_FIXTURE_SOURCE_STEP: dict[str, Any] = {
    "step_id": "fixture_source",
    "primitive": "check_fixture_source.py",
    "positional": None,
    "cwd_binding": _CWD_DIGEST_COUPLING,
    "timeout": TIMEOUT_SECONDS,
    "argv_spec": (
        ("--root", "abs_path_dir", 1, 1),
    ),
}

_PROJECT_GATES_CAPTURE_READINESS_STEP: dict[str, Any] = {
    "step_id": "capture_readiness",
    "primitive": "check_capture_readiness.py",
    "positional": None,
    "cwd_binding": _CWD_DIGEST_COUPLING,
    "timeout": TIMEOUT_SECONDS,
    "argv_spec": (
        ("--project-root", "abs_path_dir", 1, 1),
        ("--entry", "abs_path_dart", 1, 1),
        ("--scene", "abs_path_json", 1, 1),
        ("--page-source", "abs_path_plain", 1, 1),
        ("--policy-source", "abs_path_plain", 1, 1),
        ("--startup-policy-source", "abs_path_plain", 1, 1),
        ("--out", "abs_path_json", 1, 1),
    ),
}

_FAN_IN_PLAN_PREPARE_STEP: dict[str, Any] = {
    "step_id": "plan_prepare",
    "primitive": "assembly_plan_batch.py",
    "positional": "prepare",
    "cwd_binding": _CWD_DIGEST_COUPLING,
    "timeout": TIMEOUT_SECONDS,
    "argv_spec": (
        ("--spec-root", "abs_path_dir", 1, 1),
        ("--project-root", "abs_path_dir", 1, 1),
        ("--context", "abs_path_json", 1, 1),
        ("--decisions", "abs_path_json", 1, 1),
    ),
}

_FAN_IN_PLAN_APPLY_STEP: dict[str, Any] = {
    "step_id": "plan_apply",
    "primitive": "assembly_plan_batch.py",
    "positional": "apply",
    "cwd_binding": _CWD_DIGEST_COUPLING,
    "timeout": TIMEOUT_SECONDS,
    "argv_spec": (
        ("--context", "abs_path_json", 1, 1),
        ("--decisions", "abs_path_json", 1, 1),
    ),
}

_FAN_IN_SUPERVISOR_PREPARE_STEP: dict[str, Any] = {
    "step_id": "supervisor_prepare",
    "primitive": "assembly_worker_supervisor.py",
    "positional": "prepare",
    "cwd_binding": _CWD_DIGEST_COUPLING,
    "timeout": TIMEOUT_SECONDS,
    "argv_spec": (
        ("--contract", "abs_path_json", 1, 1),
    ),
}

_FAN_IN_SUPERVISOR_VERIFY_STEP: dict[str, Any] = {
    "step_id": "supervisor_verify",
    "primitive": "assembly_worker_supervisor.py",
    "positional": "verify",
    "cwd_binding": _CWD_DIGEST_COUPLING,
    "timeout": TIMEOUT_SECONDS,
    "argv_spec": (
        ("--contract", "abs_path_json", 1, 1),
    ),
}

_FAN_IN_DONE_GATE_STEP: dict[str, Any] = {
    "step_id": "done_gate",
    "primitive": "check_done_gate.py",
    "positional": None,
    "cwd_binding": _CWD_DIGEST_COUPLING,
    "timeout": TIMEOUT_SECONDS,
    "argv_spec": (
        ("--spec-root", "abs_path_dir", 1, 1),
        ("--out", "abs_path_json", 1, 1),
    ),
}

_FAN_IN_COMPLETION_ISSUE_STEP: dict[str, Any] = {
    "step_id": "completion_issue",
    "primitive": "assembly_completion.py",
    "positional": "issue",
    "cwd_binding": _CWD_DIGEST_COUPLING,
    "timeout": TIMEOUT_SECONDS,
    "argv_spec": (
        ("--spec-root", "abs_path_dir", 1, 1),
        ("--evidence", "abs_path_json", 1, 1),
    ),
}

_FAN_IN_COMPLETION_VERIFY_STEP: dict[str, Any] = {
    "step_id": "completion_verify",
    "primitive": "assembly_completion.py",
    "positional": "verify",
    "cwd_binding": _CWD_DIGEST_COUPLING,
    "timeout": TIMEOUT_SECONDS,
    "argv_spec": (
        ("--spec-root", "abs_path_dir", 1, 1),
        ("--evidence", "abs_path_json", 1, 1),
    ),
}

_OPERATION_STEPS: dict[str, tuple[dict[str, Any], ...]] = {
    "flutter.visible_codegen.v1": _VISIBLE_STEPS_SPEC,
    "flutter.fixture_codegen.v1": _FIXTURE_STEPS_SPEC,
    "flutter.trace_harness.v1": _TRACE_STEPS_SPEC,
    # packaging.v1 and test_runner.v1 are single-step variants: each plan
    # carries exactly one step whose step_id is one of the allowed
    # variant set for that operation. They are not registered in
    # _OPERATION_STEPS (which encodes fixed-order multi-step tuples);
    # their step lookup is via _STEP_SPEC_BY_KEY below.
}

# Single-step variant operations: each plan carries exactly one step
# whose step_id is one of the allowed variants for that operation.
_SINGLE_STEP_VARIANTS: dict[str, frozenset[str]] = {
    "flutter.packaging.v1": frozenset(
        {
            "copy_assets",
            "update_pubspec_asset",
            "prepare_assembly_packaging",
            "verify_assembly_packaging",
        }
    ),
    "flutter.test_runner.v1": frozenset(
        {
            "assembly_tdd_red",
            "assembly_tdd_green",
            "assembly_tdd_adopt",
            "verify_assembly_tdd",
            "retire_stale_template_tests",
        }
    ),
    "flutter.runtime_capture.v1": frozenset(
        {
            "select_device",
            "lock_acquire",
            "lock_release",
            "lock_status",
            "capture",
            "physical_preview",
        }
    ),
    "flutter.project_gates.v1": frozenset(
        {
            "interaction_wiring",
            "api_integration",
            "fixture_source",
            "capture_readiness",
        }
    ),
    "flutter.fan_in.v1": frozenset(
        {
            "plan_prepare",
            "plan_apply",
            "supervisor_prepare",
            "supervisor_verify",
            "done_gate",
            "completion_issue",
            "completion_verify",
        }
    ),
}

# Lookup table for the step spec of every known (operation_id, step_id)
# pair. verify_plan infers the exact known variant from this pair and
# rejects every other combination.
_STEP_SPEC_BY_KEY: dict[tuple[str, str], dict[str, Any]] = {}
for _spec in _VISIBLE_STEPS_SPEC:
    _STEP_SPEC_BY_KEY[("flutter.visible_codegen.v1", _spec["step_id"])] = _spec
for _spec in _FIXTURE_STEPS_SPEC:
    _STEP_SPEC_BY_KEY[("flutter.fixture_codegen.v1", _spec["step_id"])] = _spec
for _spec in _TRACE_STEPS_SPEC:
    _STEP_SPEC_BY_KEY[("flutter.trace_harness.v1", _spec["step_id"])] = _spec
for _spec in (
    _PACKAGING_COPY_ASSETS_STEP,
    _PACKAGING_UPDATE_PUBSPEC_ASSET_STEP,
    _PACKAGING_PREPARE_STEP,
    _PACKAGING_VERIFY_STEP,
):
    _STEP_SPEC_BY_KEY[("flutter.packaging.v1", _spec["step_id"])] = _spec
for _spec in (
    _TEST_RUNNER_RED_STEP,
    _TEST_RUNNER_GREEN_STEP,
    _TEST_RUNNER_ADOPT_STEP,
    _TEST_RUNNER_VERIFY_STEP,
    _TEST_RUNNER_RETIRE_STEP,
):
    _STEP_SPEC_BY_KEY[("flutter.test_runner.v1", _spec["step_id"])] = _spec
for _spec in (
    _RUNTIME_CAPTURE_SELECT_DEVICE_STEP,
    _RUNTIME_CAPTURE_LOCK_ACQUIRE_STEP,
    _RUNTIME_CAPTURE_LOCK_RELEASE_STEP,
    _RUNTIME_CAPTURE_LOCK_STATUS_STEP,
    _RUNTIME_CAPTURE_CAPTURE_STEP,
    _RUNTIME_CAPTURE_PHYSICAL_PREVIEW_STEP,
):
    _STEP_SPEC_BY_KEY[("flutter.runtime_capture.v1", _spec["step_id"])] = _spec
for _spec in (
    _PROJECT_GATES_INTERACTION_WIRING_STEP,
    _PROJECT_GATES_API_INTEGRATION_STEP,
    _PROJECT_GATES_FIXTURE_SOURCE_STEP,
    _PROJECT_GATES_CAPTURE_READINESS_STEP,
):
    _STEP_SPEC_BY_KEY[("flutter.project_gates.v1", _spec["step_id"])] = _spec
for _spec in (
    _FAN_IN_PLAN_PREPARE_STEP,
    _FAN_IN_PLAN_APPLY_STEP,
    _FAN_IN_SUPERVISOR_PREPARE_STEP,
    _FAN_IN_SUPERVISOR_VERIFY_STEP,
    _FAN_IN_DONE_GATE_STEP,
    _FAN_IN_COMPLETION_ISSUE_STEP,
    _FAN_IN_COMPLETION_VERIFY_STEP,
):
    _STEP_SPEC_BY_KEY[("flutter.fan_in.v1", _spec["step_id"])] = _spec
del _spec

# Normalize every step spec so that cwd_binding and positional have a
# concrete value. The P2d2a step specs (visible/fixture/trace) carry no
# positional subcommand and bind cwd to the canonical project_root with
# at least one absolute argv path equal to cwd or a strict descendant.
for _normalize_spec in _STEP_SPEC_BY_KEY.values():
    _normalize_spec.setdefault("positional", None)
    _normalize_spec.setdefault("cwd_binding", _CWD_PROJECT_ROOT_OR_DESCENDANT)
del _normalize_spec

# ---------------------------------------------------------------------------
# Forbidden caller keys (recursively).
# Any of these names anywhere in caller data is an integrity violation.
# ---------------------------------------------------------------------------

_FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "command",
        "shell",
        "env",
        "environment",
        "argv",
        "args",
        "executable",
        "interpreter",
        "runner",
        "prompt",
        "script",
        "script_path",
        "operation_id",
    }
)

# ---------------------------------------------------------------------------
# Regexes / enum sets.
# ---------------------------------------------------------------------------

_PACKAGE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_DART_CLASS_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_PACKAGE_IMPORT_RE = re.compile(r"^package:[a-z][a-z0-9_]*/.+\.dart$")
_ASSET_PREFIX_RE = re.compile(r"^assets/icp/[a-z][a-z0-9_]*$")
_SAFE_AREA_ENUMS: frozenset[str] = frozenset({"edge_to_edge", "inset_content"})
_SLOTS_MAX = 32

# P2e1 alignment: the frozen Flutter selection manifest derives the run
# root as ``<project>/.iff/icp_runs/<batch_id>``. The plan builder must
# accept that exact internal path so a binding can re-use the manifest's
# own run root, while continuing to reject every other project-internal
# path. The batch grammar matches the freezer's safe batch id rule
# (``^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$``) so ``.``, ``..``, slashes,
# backslashes, whitespace, and overlong forms can never collapse or
# escape the run directory. Both ``run_root`` and ``project_root`` are
# already canonical real non-symlink directories through ``_validate_root_path``
# before this rule is consulted, so the lexical structure check below
# cannot be fooled by a symlinked ``.iff`` / ``icp_runs`` / batch.
#
# The grammar is enforced with :meth:`re.Pattern.fullmatch` (NOT
# :meth:`re.Pattern.match`): Python's ``$`` anchor may match before a
# final trailing newline, so ``re.match(r'...$')`` would accept a value
# ending in ``\n``. ``fullmatch`` is the exact whole-string contract
# documented above; macOS permits a directory name containing a newline,
# so this is a real on-disk attack surface, not a theoretical one.
_INTERNAL_RUN_STATE_DIRNAME = ".iff"
_INTERNAL_RUN_PARENT_DIRNAME = "icp_runs"
_INTERNAL_RUN_BATCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")

# P2d2b fixed-token literals carried in argv (the only allowed value
# for the corresponding flag).
_FIXED_FAILURE_KIND = "missing_feature_behavior"
_FIXED_AUTHORIZATION = "preexisting-green"

# P2d2b request action/phase enumerations.
_PACKAGING_ACTIONS: frozenset[str] = frozenset(
    {"copy_assets", "update_pubspec_asset", "prepare", "verify"}
)
_TEST_RUNNER_PHASES: frozenset[str] = frozenset(
    {"red", "green", "adopt", "verify", "retire_stale_template_tests"}
)

# P2d2c request action enumerations. The supervisor ``run`` subcommand is
# deliberately NOT a member of the fan_in action set because it accepts an
# arbitrary trailing command.
_RUNTIME_CAPTURE_ACTIONS: frozenset[str] = frozenset(
    {
        "select_device",
        "lock_acquire",
        "lock_release",
        "lock_status",
        "capture",
        "physical_preview",
    }
)
_RUNTIME_CAPTURE_NEEDS_SPEC_ROOT: frozenset[str] = frozenset(
    {"select_device", "capture", "physical_preview"}
)
_PROJECT_GATES_ACTIONS: frozenset[str] = frozenset(
    {"interaction_wiring", "api_integration", "fixture_source", "capture_readiness"}
)
_PROJECT_GATES_NEEDS_SPEC_ROOT: frozenset[str] = frozenset(
    {"interaction_wiring", "api_integration", "capture_readiness"}
)
_FAN_IN_ACTIONS: frozenset[str] = frozenset(
    {
        "plan_prepare",
        "plan_apply",
        "supervisor_prepare",
        "supervisor_verify",
        "done_gate",
        "completion_issue",
        "completion_verify",
    }
)
# The three append-only P2d2c operation IDs.
_P2D2C_OPERATIONS: frozenset[str] = frozenset(
    {
        "flutter.runtime_capture.v1",
        "flutter.project_gates.v1",
        "flutter.fan_in.v1",
    }
)


class OperationPlanError(ValueError):
    """A local trusted-operation-plan failure.

    Raised for any capsule verification error, manifest load/shape error,
    request schema/path/identifier validation error, plan build/validate
    error, or argv tamper detection. Generic (non-:class:`OperationPlanError`)
    exceptions are converted at the public API boundary to instances of
    this class whose message exposes the original exception type name
    only — arbitrary exception text is never leaked.
    """


# ---------------------------------------------------------------------------
# Small deterministic helpers (canonical JSON, digests, strict decode).
# ---------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            raise OperationPlanError(f"duplicate JSON key: {key!r}")
        seen.add(key)
    return dict(pairs)


def _decode_json_strict(raw: bytes, role: str) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OperationPlanError(f"{role}: not UTF-8: {type(exc).__name__}") from exc
    try:
        obj = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except OperationPlanError:
        raise
    except json.JSONDecodeError as exc:
        raise OperationPlanError(f"{role}: not valid JSON") from exc
    if not isinstance(obj, dict):
        raise OperationPlanError(
            f"{role}: root must be a JSON object, got {type(obj).__name__}"
        )
    return obj


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value.islower()
        and all(c in "0123456789abcdef" for c in value)
    )


def _is_safe_basename(name: Any) -> bool:
    if not isinstance(name, str) or not name:
        return False
    if "/" in name or "\\" in name or name in {".", ".."} or "\x00" in name:
        return False
    if name != os.path.basename(name):
        return False
    return name.endswith(".py")


def _check_nonsymlink_dir(path: Path, role: str) -> None:
    try:
        if path.is_symlink():
            raise OperationPlanError(f"{role}: refusing symlink: {path}")
        st = path.lstat()
    except OSError as exc:
        raise OperationPlanError(f"{role}: cannot lstat: {type(exc).__name__}") from exc
    if not stat.S_ISDIR(st.st_mode):
        raise OperationPlanError(f"{role}: not a directory: {path}")


def _check_nonsymlink_regular_file(path: Path, role: str) -> None:
    try:
        if path.is_symlink():
            raise OperationPlanError(f"{role}: refusing symlink: {path}")
        st = path.lstat()
    except OSError as exc:
        raise OperationPlanError(f"{role}: cannot lstat: {type(exc).__name__}") from exc
    if not stat.S_ISREG(st.st_mode):
        raise OperationPlanError(f"{role}: not a regular file: {path}")


# ---------------------------------------------------------------------------
# Forbidden-key recursive check.
# ---------------------------------------------------------------------------


def _reject_forbidden_keys(obj: Any, location: str) -> None:
    """Walk ``obj`` and reject any forbidden executable/command/argv/shell
    key anywhere in caller data."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise OperationPlanError(
                    f"{location}: non-string key {key!r}"
                )
            here = f"{location}/{key}" if location else key
            if key in _FORBIDDEN_KEYS:
                raise OperationPlanError(f"{location}: forbidden key {key!r}")
            _reject_forbidden_keys(value, here)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _reject_forbidden_keys(item, f"{location}[{i}]")
    elif isinstance(obj, (str, int, float, bool)) or obj is None:
        return
    else:
        # Unsupported types (set, bytes, custom objects) are rejected.
        raise OperationPlanError(
            f"{location}: unsupported value type {type(obj).__name__}"
        )


# ---------------------------------------------------------------------------
# Capsule verification (delegated to the P2a runtime gate).
#
# Two explicit guarded stages so a same-name exception class raised before
# the fixed verifier module loaded can never be mis-trusted as a known
# capsule-integrity error: see the P2d1 preflight module for the pattern.
# ---------------------------------------------------------------------------


_VERIFY_MODULE: Any = None


def _load_verify_module():
    """Load ``verify_vendor_iff_v1`` by file path (no sys.path mutation)."""
    global _VERIFY_MODULE
    if _VERIFY_MODULE is None:
        _check_nonsymlink_regular_file(VERIFY_TOOL, "verify_vendor_iff_v1.py")
        spec = importlib.util.spec_from_file_location(
            "verify_vendor_iff_v1_p2d2a", str(VERIFY_TOOL)
        )
        if spec is None or spec.loader is None:
            raise OperationPlanError("cannot load verify_vendor_iff_v1 module spec")
        module = importlib.util.module_from_spec(spec)
        sys.modules["verify_vendor_iff_v1_p2d2a"] = module
        spec.loader.exec_module(module)
        _VERIFY_MODULE = module
    return _VERIFY_MODULE


def _verify_capsule() -> dict[str, Any]:
    """Verify the installed vendored capsule via the P2a runtime gate.

    Returns the canonical capsule-success payload. Any integrity violation
    surfaces as an :class:`OperationPlanError`. Never imports, reads,
    executes, or follows a symlink into ``iff/**``.
    """
    # Stage 1: load the fixed verifier module by file path. Any exception
    # here is untrusted.
    try:
        verifier_module = _load_verify_module()
    except OperationPlanError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise OperationPlanError(
            f"capsule verification raised {type(exc).__name__}"
        ) from exc

    # Stage 2: the fixed verifier module loaded successfully. Only now is
    # its ``CapsuleIntegrityError`` class trustworthy for isinstance-based
    # classification.
    try:
        return verifier_module.verify_skill(ICP_ROOT)
    except verifier_module.CapsuleIntegrityError as exc:
        raise OperationPlanError(f"capsule verification failed: {exc}") from exc
    except OperationPlanError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise OperationPlanError(
            f"capsule verification raised {type(exc).__name__}"
        ) from exc


# ---------------------------------------------------------------------------
# Manifest load + shape validation.
# ---------------------------------------------------------------------------


def _load_manifest() -> dict[str, Any]:
    _check_nonsymlink_regular_file(MANIFEST_PATH, "iff-v1-vendor.json")
    manifest = _decode_json_strict(MANIFEST_PATH.read_bytes(), "iff-v1-vendor.json")
    if manifest.get("kind") != "icp.iff-v1-vendor-capsule":
        raise OperationPlanError(
            f"manifest kind not canonical: {manifest.get('kind')!r}"
        )
    if manifest.get("schema_version") != 1:
        raise OperationPlanError(
            f"manifest schema_version not canonical: "
            f"{manifest.get('schema_version')!r}"
        )
    if manifest.get("capsule_root") != "vendor/iff_v1":
        raise OperationPlanError(
            f"manifest capsule_root not canonical: "
            f"{manifest.get('capsule_root')!r}"
        )
    scripts = manifest.get("scripts")
    if not isinstance(scripts, list) or not scripts:
        raise OperationPlanError("manifest scripts missing/empty")
    return manifest


def _manifest_sha_map(manifest: dict[str, Any]) -> dict[str, str]:
    """Map basename -> sha256 from the manifest's scripts list.

    Rejects duplicates, unsafe names, and malformed SHAs up front so the
    plan builder never sees an ambiguous lookup.
    """
    out: dict[str, str] = {}
    for entry in manifest["scripts"]:
        if not isinstance(entry, dict):
            raise OperationPlanError("manifest script entry not an object")
        name = entry.get("name")
        if not _is_safe_basename(name):
            raise OperationPlanError(f"manifest script name unsafe: {name!r}")
        if name in out:
            raise OperationPlanError(f"manifest script duplicate: {name!r}")
        sha = entry.get("sha256")
        if not _is_sha256_hex(sha):
            raise OperationPlanError(
                f"manifest script {name} sha256 malformed: {sha!r}"
            )
        out[name] = sha
    return out


def _lookup_primitive_sha(sha_map: dict[str, str], primitive: str) -> str:
    if primitive not in sha_map:
        raise OperationPlanError(f"primitive {primitive!r} missing from manifest")
    return sha_map[primitive]


def _lookup_platform_script_sha(
    primitive: str, sha_map: dict[str, str]
) -> str:
    """Recompute the SHA-256 of the fixed platform script ``primitive``.

    The platform script must:
    * be a safe ``.py`` basename;
    * NOT collide by basename with any capsule-manifest primitive (the
      capsule manifest remains the sole trust root for capsule scripts);
    * exist as a regular non-symlink file under PLATFORM_SCRIPTS_DIR;
    * strict-resolve to its lexical path (no symlinked ancestor).

    The SHA-256 is recomputed from the file bytes on every call so any
    drift fails closed at the next build/verify. Accepts NO caller-
    provided script root or script path override.
    """
    if not _is_safe_basename(primitive):
        raise OperationPlanError(
            f"platform primitive not a safe basename: {primitive!r}"
        )
    if primitive in sha_map:
        raise OperationPlanError(
            f"platform primitive {primitive!r} collides with capsule manifest"
        )
    path = PLATFORM_SCRIPTS_DIR / primitive
    _check_nonsymlink_regular_file(path, f"platform primitive {primitive!r}")
    # Strict-resolve identity check (rejects a symlinked ancestor under
    # PLATFORM_SCRIPTS_DIR redirecting the lexical path).
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise OperationPlanError(
            f"platform primitive {primitive!r} resolve failed"
        ) from exc
    except OSError as exc:
        raise OperationPlanError(
            f"platform primitive {primitive!r} resolve: {type(exc).__name__}"
        ) from exc
    if resolved != path:
        raise OperationPlanError(
            f"platform primitive {primitive!r} path differs from strict resolve"
        )
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise OperationPlanError(
            f"platform primitive {primitive!r} unreadable: {type(exc).__name__}"
        ) from exc


def _resolve_script_path_and_sha(
    spec: dict[str, Any], primitive: str, sha_map: dict[str, str]
) -> tuple[str, str]:
    """Resolve the script path and SHA for a step from its closed origin.

    Returns ``(script_path_str, sha256_hex)``. The origin is recovered
    from the fixed internal step spec (never from the plan or request).
    """
    origin = spec.get("script_origin", _ORIGIN_CAPSULE)
    if origin == _ORIGIN_CAPSULE:
        return (
            str(CAPSULE_SCRIPTS_DIR / primitive),
            _lookup_primitive_sha(sha_map, primitive),
        )
    if origin == _ORIGIN_PLATFORM:
        return (
            str(PLATFORM_SCRIPTS_DIR / primitive),
            _lookup_platform_script_sha(primitive, sha_map),
        )
    raise OperationPlanError(
        f"unknown script_origin {origin!r} for primitive {primitive!r}"
    )


# ---------------------------------------------------------------------------
# Common path / identifier validators.
# ---------------------------------------------------------------------------


def _validate_root_path(value: Any, role: str) -> Path:
    """Validate an absolute, lexically normalized, existing non-symlink
    real directory. Returns the resolved :class:`Path`."""
    if isinstance(value, (bytes, bytearray)):
        raise OperationPlanError(f"{role}: must be str, got bytes")
    if not isinstance(value, str):
        raise OperationPlanError(
            f"{role}: must be str, got {type(value).__name__}"
        )
    raw = Path(value)
    if not raw.is_absolute():
        raise OperationPlanError(f"{role}: not absolute: {value!r}")
    if any(part == ".." for part in raw.parts):
        raise OperationPlanError(f"{role}: contains '..': {value!r}")
    if os.path.normpath(value) != value:
        raise OperationPlanError(f"{role}: not lexically normalized: {value!r}")
    try:
        resolved = raw.resolve(strict=True)
    except FileNotFoundError as exc:
        raise OperationPlanError(f"{role}: does not exist: {value!r}") from exc
    except RuntimeError as exc:
        raise OperationPlanError(f"{role}: resolve loop: {type(exc).__name__}") from exc
    except OSError as exc:
        raise OperationPlanError(f"{role}: resolve failed: {type(exc).__name__}") from exc
    if resolved != raw:
        raise OperationPlanError(
            f"{role}: supplied path differs from strict resolve "
            f"(symlinked root or ancestor)"
        )
    _check_nonsymlink_dir(resolved, role)
    return resolved


def _is_strictly_inside(child: Path, parent: Path) -> bool:
    """True if ``child`` is lexically contained under ``parent`` as a
    strict descendant. Uses ``relative_to`` in a try/except that catches
    only ``ValueError`` (NOT :class:`OperationPlanError`, which is itself
    a ``ValueError`` subclass)."""
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return child != parent


def _check_root_nesting(project_root: Path, run_root: Path) -> None:
    """Validate the project_root / run_root relationship.

    Accepted shapes:

    * ``run_root`` disjoint from ``project_root`` (the pre-P2e1
      project-external layout; retained for compatibility).
    * ``run_root`` nested inside ``project_root`` **only** when its
      project-relative path is exactly
      ``.iff/icp_runs/<batch_id>`` — the frozen Flutter manifest's
      canonical internal run root. ``<batch_id>`` must match the
      freezer's safe grammar ``^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$``.

    Rejected: equality; project root nested inside run root; any other
    project-internal path (``lib``, ``test``, ``.dart_tool``, ``.iff``,
    ``.iff/icp_runs``, ``.iff/icp_runs/<batch>/extra``, prefix
    lookalikes such as ``.iff2`` or ``icp_runs_``). Symlinked
    ``.iff`` / ``icp_runs`` / batch are rejected earlier by
    :func:`_validate_root_path` (both roots are canonical real
    non-symlink directories before this rule runs).
    """
    if run_root == project_root:
        raise OperationPlanError("run_root must differ from project_root")
    if _is_strictly_inside(project_root, run_root):
        raise OperationPlanError("project_root must not be nested inside run_root")
    if not _is_strictly_inside(run_root, project_root):
        # Disjoint project-external run root: accepted (compatibility).
        return
    # run_root is strictly inside project_root. Require the exact
    # ``.iff/icp_runs/<batch_id>`` internal manifest path.
    try:
        rel = run_root.relative_to(project_root)
    except ValueError as exc:  # pragma: no cover - _is_strictly_inside guards
        raise OperationPlanError(
            "run_root must not be nested inside project_root"
        ) from exc
    parts = rel.parts
    if (
        len(parts) == 3
        and parts[0] == _INTERNAL_RUN_STATE_DIRNAME
        and parts[1] == _INTERNAL_RUN_PARENT_DIRNAME
        and _INTERNAL_RUN_BATCH_RE.fullmatch(parts[2])
    ):
        return
    raise OperationPlanError(
        "run_root nested inside project_root must be the exact frozen "
        "manifest path .iff/icp_runs/<batch_id>"
    )


def _check_posix_relative(rel: Any, role: str) -> None:
    """Reject anything that is not a strict POSIX relative path string:
    no absolute paths, empty components, ``.``/``..``, backslashes, NUL,
    URI schemes, or repeated separators."""
    if not isinstance(rel, str):
        raise OperationPlanError(
            f"{role}: must be a string, got {type(rel).__name__}"
        )
    if not rel:
        raise OperationPlanError(f"{role}: empty path")
    if rel.startswith("/"):
        raise OperationPlanError(f"{role}: absolute path not allowed: {rel!r}")
    if "\\" in rel:
        raise OperationPlanError(f"{role}: backslash not allowed: {rel!r}")
    if "\x00" in rel:
        raise OperationPlanError(f"{role}: NUL not allowed: {rel!r}")
    if "://" in rel:
        raise OperationPlanError(f"{role}: URI scheme not allowed: {rel!r}")
    parts = rel.split("/")
    for p in parts:
        if p == "" or p == "." or p == "..":
            raise OperationPlanError(
                f"{role}: invalid component {p!r} in {rel!r}"
            )


def _validate_existing_file_under_root(
    rel: Any, root: Path, ext: str | None, role: str
) -> str:
    """Validate a POSIX relative path that resolves below ``root`` and
    must already exist as a non-symlink regular file. Every component must
    be non-symlink. Returns the absolute path string."""
    _check_posix_relative(rel, role)
    if ext is not None and not rel.endswith(ext):
        raise OperationPlanError(
            f"{role}: must end with {ext!r}: {rel!r}"
        )
    parts = rel.split("/")
    current = root
    last = len(parts) - 1
    for index, part in enumerate(parts):
        candidate = current / part
        try:
            if candidate.is_symlink():
                raise OperationPlanError(
                    f"{role}: refusing symlinked component {part!r}"
                )
        except OSError as exc:
            raise OperationPlanError(
                f"{role}: cannot lstat {part!r}: {type(exc).__name__}"
            ) from exc
        try:
            st = candidate.lstat()
        except FileNotFoundError as exc:
            raise OperationPlanError(
                f"{role}: missing component {part!r}"
            ) from exc
        except OSError as exc:
            raise OperationPlanError(
                f"{role}: cannot stat {part!r}: {type(exc).__name__}"
            ) from exc
        if index < last:
            if not stat.S_ISDIR(st.st_mode):
                raise OperationPlanError(
                    f"{role}: ancestor {part!r} not a directory"
                )
        else:
            if not stat.S_ISREG(st.st_mode):
                raise OperationPlanError(
                    f"{role}: leaf {part!r} not a regular file"
                )
        current = candidate
    # Strict-resolve the leaf and verify no path escape. Every component
    # is non-symlink and the root is canonical, so the resolved path
    # equals the supplied path; any divergence is an escape attempt.
    try:
        resolved = current.resolve(strict=True)
    except FileNotFoundError as exc:
        raise OperationPlanError(f"{role}: missing after walk") from exc
    except OSError as exc:
        raise OperationPlanError(f"{role}: resolve failed: {type(exc).__name__}") from exc
    if resolved != current:
        raise OperationPlanError(f"{role}: path escape after resolve")
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise OperationPlanError(f"{role}: not contained in root") from exc
    return str(current)


def _validate_output_path_under_root(
    rel: Any, root: Path, ext: str | None, role: str
) -> str:
    """Validate a POSIX relative path that resolves below ``root`` and is
    an output target. Existing outputs may be non-symlink regular files;
    absent outputs are allowed only when the nearest existing ancestor is
    a non-symlink directory and the full lexical path remains contained.
    Directories, symlinks, path escape, and any symlinked component are
    rejected. Returns the absolute path string."""
    _check_posix_relative(rel, role)
    if ext is not None and not rel.endswith(ext):
        raise OperationPlanError(
            f"{role}: must end with {ext!r}: {rel!r}"
        )
    parts = rel.split("/")
    # full_leaf is built purely lexically; by construction (clean parts)
    # it is contained under root.
    full_leaf = root
    for part in parts:
        full_leaf = full_leaf / part
    current = root
    last = len(parts) - 1
    for index, part in enumerate(parts):
        candidate = current / part
        try:
            if candidate.is_symlink():
                raise OperationPlanError(
                    f"{role}: refusing symlinked component {part!r}"
                )
        except OSError as exc:
            raise OperationPlanError(
                f"{role}: cannot lstat {part!r}: {type(exc).__name__}"
            ) from exc
        try:
            st = candidate.lstat()
        except FileNotFoundError:
            # Absent component. The nearest existing ancestor is
            # ``current`` (already verified as a non-symlink dir). All
            # further components are absent by definition. The full
            # lexical path is contained by construction.
            return str(full_leaf)
        except OSError as exc:
            raise OperationPlanError(
                f"{role}: cannot stat {part!r}: {type(exc).__name__}"
            ) from exc
        if index < last:
            if not stat.S_ISDIR(st.st_mode):
                raise OperationPlanError(
                    f"{role}: ancestor {part!r} not a directory"
                )
            current = candidate
        else:
            # Leaf exists.
            if not stat.S_ISREG(st.st_mode):
                raise OperationPlanError(
                    f"{role}: existing output {part!r} not a regular file"
                )
            current = candidate
    return str(full_leaf)


def _validate_regex(value: Any, regex: re.Pattern[str], role: str) -> str:
    if not isinstance(value, str):
        raise OperationPlanError(
            f"{role}: must be a string, got {type(value).__name__}"
        )
    if not regex.match(value):
        raise OperationPlanError(
            f"{role}: does not match {regex.pattern!r}: {value!r}"
        )
    return value


def _validate_existing_dir_under_root(
    rel: Any, root: Path, role: str
) -> str:
    """Validate a POSIX relative path that resolves below ``root`` and
    must already exist as a non-symlink real directory. Every component
    must be non-symlink. Returns the absolute path string."""
    _check_posix_relative(rel, role)
    parts = rel.split("/")
    current = root
    for index, part in enumerate(parts):
        candidate = current / part
        try:
            if candidate.is_symlink():
                raise OperationPlanError(
                    f"{role}: refusing symlinked component {part!r}"
                )
        except OSError as exc:
            raise OperationPlanError(
                f"{role}: cannot lstat {part!r}: {type(exc).__name__}"
            ) from exc
        try:
            st = candidate.lstat()
        except FileNotFoundError as exc:
            raise OperationPlanError(
                f"{role}: missing component {part!r}"
            ) from exc
        except OSError as exc:
            raise OperationPlanError(
                f"{role}: cannot stat {part!r}: {type(exc).__name__}"
            ) from exc
        if not stat.S_ISDIR(st.st_mode):
            raise OperationPlanError(
                f"{role}: component {part!r} not a directory"
            )
        current = candidate
    # Strict-resolve and verify containment. Every component is
    # non-symlink and the root is canonical, so any divergence is an
    # escape attempt.
    try:
        resolved = current.resolve(strict=True)
    except FileNotFoundError as exc:
        raise OperationPlanError(f"{role}: missing after walk") from exc
    except OSError as exc:
        raise OperationPlanError(f"{role}: resolve failed: {type(exc).__name__}") from exc
    if resolved != current:
        raise OperationPlanError(f"{role}: path escape after resolve")
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise OperationPlanError(f"{role}: not contained in root") from exc
    return str(current)


def _validate_existing_path_under_root(
    rel: Any, root: Path, role: str
) -> str:
    """Validate a POSIX relative path that resolves below ``root`` and
    must already exist as a non-symlink regular file OR a non-symlink
    real directory. Every component must be non-symlink. Returns the
    absolute path string."""
    _check_posix_relative(rel, role)
    parts = rel.split("/")
    current = root
    last = len(parts) - 1
    for index, part in enumerate(parts):
        candidate = current / part
        try:
            if candidate.is_symlink():
                raise OperationPlanError(
                    f"{role}: refusing symlinked component {part!r}"
                )
        except OSError as exc:
            raise OperationPlanError(
                f"{role}: cannot lstat {part!r}: {type(exc).__name__}"
            ) from exc
        try:
            st = candidate.lstat()
        except FileNotFoundError as exc:
            raise OperationPlanError(
                f"{role}: missing component {part!r}"
            ) from exc
        except OSError as exc:
            raise OperationPlanError(
                f"{role}: cannot stat {part!r}: {type(exc).__name__}"
            ) from exc
        if index < last:
            if not stat.S_ISDIR(st.st_mode):
                raise OperationPlanError(
                    f"{role}: ancestor {part!r} not a directory"
                )
        else:
            if not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
                raise OperationPlanError(
                    f"{role}: leaf {part!r} not a regular file or directory"
                )
        current = candidate
    try:
        resolved = current.resolve(strict=True)
    except FileNotFoundError as exc:
        raise OperationPlanError(f"{role}: missing after walk") from exc
    except OSError as exc:
        raise OperationPlanError(f"{role}: resolve failed: {type(exc).__name__}") from exc
    if resolved != current:
        raise OperationPlanError(f"{role}: path escape after resolve")
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise OperationPlanError(f"{role}: not contained in root") from exc
    return str(current)


def _validate_target_dir_under_root(
    rel: Any, root: Path, role: str
) -> str:
    """Validate a POSIX relative path that resolves below ``root`` and is
    a directory target. The target may exist as a non-symlink real
    directory or be absent (when every existing ancestor is a non-symlink
    directory). Existing regular files, symlinks, path escape, and any
    symlinked component are rejected. Returns the absolute path string."""
    _check_posix_relative(rel, role)
    parts = rel.split("/")
    # full_leaf is built purely lexically; by construction (clean parts)
    # it is contained under root.
    full_leaf = root
    for part in parts:
        full_leaf = full_leaf / part
    current = root
    last = len(parts) - 1
    for index, part in enumerate(parts):
        candidate = current / part
        try:
            if candidate.is_symlink():
                raise OperationPlanError(
                    f"{role}: refusing symlinked component {part!r}"
                )
        except OSError as exc:
            raise OperationPlanError(
                f"{role}: cannot lstat {part!r}: {type(exc).__name__}"
            ) from exc
        try:
            st = candidate.lstat()
        except FileNotFoundError:
            # Absent component. Nearest existing ancestor is ``current``
            # (already verified non-symlink dir). All further components
            # are absent by definition. Full lexical path is contained
            # by construction.
            return str(full_leaf)
        except OSError as exc:
            raise OperationPlanError(
                f"{role}: cannot stat {part!r}: {type(exc).__name__}"
            ) from exc
        if index < last:
            if not stat.S_ISDIR(st.st_mode):
                raise OperationPlanError(
                    f"{role}: ancestor {part!r} not a directory"
                )
            current = candidate
        else:
            # Leaf exists.
            if not stat.S_ISDIR(st.st_mode):
                raise OperationPlanError(
                    f"{role}: existing target {part!r} not a directory"
                )
            current = candidate
    return str(full_leaf)


def _check_project_pubspec(project_root: Path) -> str:
    """The fixed project pubspec at ``${project_root}/pubspec.yaml`` must
    be an existing non-symlink regular file with a safe basename. Returns
    its absolute path string. The pubspec is never caller-selectable."""
    pubspec_path = project_root / "pubspec.yaml"
    role = "project pubspec.yaml"
    try:
        if pubspec_path.is_symlink():
            raise OperationPlanError(f"{role}: refusing symlink: {pubspec_path}")
        st = pubspec_path.lstat()
    except FileNotFoundError as exc:
        raise OperationPlanError(f"{role}: missing: {pubspec_path}") from exc
    except OSError as exc:
        raise OperationPlanError(f"{role}: cannot lstat: {type(exc).__name__}") from exc
    if not stat.S_ISREG(st.st_mode):
        raise OperationPlanError(f"{role}: not a regular file: {pubspec_path}")
    return str(pubspec_path)


def _check_project_dir(project_root: Path, name: str) -> str:
    """A fixed existing non-symlink directory at
    ``${project_root}/<name>``. Returns its absolute path string."""
    path = project_root / name
    role = f"project {name}"
    try:
        if path.is_symlink():
            raise OperationPlanError(f"{role}: refusing symlink: {path}")
        st = path.lstat()
    except FileNotFoundError as exc:
        raise OperationPlanError(f"{role}: missing: {path}") from exc
    except OSError as exc:
        raise OperationPlanError(f"{role}: cannot lstat: {type(exc).__name__}") from exc
    if not stat.S_ISDIR(st.st_mode):
        raise OperationPlanError(f"{role}: not a directory: {path}")
    return str(path)


def _check_project_entry(project_root: Path) -> str:
    """The fixed project entry at ``${project_root}/lib/main.dart`` must
    be an existing non-symlink regular file. Reuses the established
    nofollow-under-root validator so a symlinked ``lib`` ancestor (not
    just a symlinked ``main.dart`` leaf) is rejected component-by-
    component."""
    return _validate_existing_file_under_root(
        "lib/main.dart", project_root, ".dart", "project entry"
    )


def _check_fixed_spec_input(spec_root: Path, basename: str, role: str) -> str:
    """A fixed existing non-symlink regular file at
    ``${spec_root}/<basename>``. The basename is a fixed code literal."""
    path = spec_root / basename
    try:
        if path.is_symlink():
            raise OperationPlanError(f"{role}: refusing symlink: {path}")
        st = path.lstat()
    except FileNotFoundError as exc:
        raise OperationPlanError(f"{role}: missing: {path}") from exc
    except OSError as exc:
        raise OperationPlanError(f"{role}: cannot lstat: {type(exc).__name__}") from exc
    if not stat.S_ISREG(st.st_mode):
        raise OperationPlanError(f"{role}: not a regular file: {path}")
    return str(path)


def _check_fixed_spec_output(
    spec_root: Path, basename: str, role: str
) -> str:
    """A fixed output target at ``${spec_root}/<basename>``. May be an
    existing non-symlink regular file or absent. A directory, symlink, or
    non-regular leaf is rejected."""
    path = spec_root / basename
    try:
        if path.is_symlink():
            raise OperationPlanError(f"{role}: refusing symlink: {path}")
        st = path.lstat()
    except FileNotFoundError:
        return str(path)
    except OSError as exc:
        raise OperationPlanError(f"{role}: cannot lstat: {type(exc).__name__}") from exc
    if not stat.S_ISREG(st.st_mode):
        raise OperationPlanError(f"{role}: not a regular file: {path}")
    return str(path)


def _check_device_lock_path(project_root: Path) -> str:
    """The fixed device lock directory target at
    ``${project_root}/.icp/device.lock``. May be an existing non-symlink
    directory (stale lock) or absent. An existing regular file, symlink,
    or non-directory leaf is rejected."""
    rel = ".icp/device.lock"
    return _validate_target_dir_under_root(rel, project_root, "device lock")


def _validate_abs_existing_file_under_root(
    value: Any, root: Path, role: str
) -> str:
    """Validate an absolute canonical existing non-symlink regular file
    strictly within ``root``. Reuses the relative validator after a
    lexical containment check, so the no-symlink/no-escape guarantees of
    ``_validate_existing_file_under_root`` apply."""
    if isinstance(value, (bytes, bytearray)):
        raise OperationPlanError(f"{role}: must be str, got bytes")
    if not isinstance(value, str):
        raise OperationPlanError(
            f"{role}: must be str, got {type(value).__name__}"
        )
    if not os.path.isabs(value):
        raise OperationPlanError(f"{role}: not absolute: {value!r}")
    if "\\" in value:
        raise OperationPlanError(f"{role}: backslash not allowed: {value!r}")
    if "\x00" in value:
        raise OperationPlanError(f"{role}: NUL not allowed: {value!r}")
    if any(part == ".." for part in Path(value).parts):
        raise OperationPlanError(f"{role}: contains '..': {value!r}")
    if os.path.normpath(value) != value:
        raise OperationPlanError(f"{role}: not lexically normalized: {value!r}")
    raw = Path(value)
    try:
        rel = raw.relative_to(root)
    except ValueError as exc:
        raise OperationPlanError(f"{role}: not within project_root") from exc
    if str(rel) == ".":
        raise OperationPlanError(f"{role}: equals project_root")
    return _validate_existing_file_under_root(str(rel), root, None, role)


def _check_subtree_relative(rel: str, prefix: str, role: str) -> None:
    """Reject a POSIX relative path that does not begin with ``prefix/``
    (or equal an illegal exact ``prefix``). Used to confine ``assets/``
    and ``test/`` subtrees."""
    if rel == prefix:
        raise OperationPlanError(
            f"{role}: must be strictly below {prefix!r}: {rel!r}"
        )
    if not rel.startswith(prefix + "/"):
        raise OperationPlanError(
            f"{role}: must begin with {prefix + '/'!r}: {rel!r}"
        )


def _construct_package_import(package_name: str, rel_path: str) -> str:
    """Construct ``package:<package_name>/<rel_path with a leading lib/
    removed>``."""
    if rel_path.startswith("lib/"):
        rel = rel_path[len("lib/"):]
    else:
        rel = rel_path
    return f"package:{package_name}/{rel}"


# ---------------------------------------------------------------------------
# visible_codegen request validation + step building.
# ---------------------------------------------------------------------------


_VISIBLE_REQUEST_KEYS = frozenset(
    {
        "project_root",
        "run_root",
        "package_name",
        "feature_id",
        "render_plan",
        "scene",
        "classification",
        "component_manifest",
        "canvas_out",
        "colors_out",
        "colors_import_path",
        "implementation_map_out",
        "status_bar_out",
        "canvas_class_name",
        "status_bar_class_name",
    }
)


def _validate_visible_request(request: dict[str, Any]) -> dict[str, Any]:
    actual = set(request.keys())
    if actual != _VISIBLE_REQUEST_KEYS:
        extra = actual - _VISIBLE_REQUEST_KEYS
        missing = _VISIBLE_REQUEST_KEYS - actual
        raise OperationPlanError(
            f"visible_codegen request keys mismatch: "
            f"extra={sorted(extra)} missing={sorted(missing)}"
        )

    project_root = _validate_root_path(request["project_root"], "project_root")
    run_root = _validate_root_path(request["run_root"], "run_root")
    _check_root_nesting(project_root, run_root)

    package_name = _validate_regex(
        request["package_name"], _PACKAGE_RE, "package_name"
    )
    feature_id = _validate_regex(
        request["feature_id"], _PACKAGE_RE, "feature_id"
    )
    canvas_class_name = _validate_regex(
        request["canvas_class_name"], _DART_CLASS_RE, "canvas_class_name"
    )
    status_bar_class_name = _validate_regex(
        request["status_bar_class_name"], _DART_CLASS_RE, "status_bar_class_name"
    )

    render_plan_abs = _validate_existing_file_under_root(
        request["render_plan"], run_root, ".json", "render_plan"
    )
    scene_abs = _validate_existing_file_under_root(
        request["scene"], run_root, ".json", "scene"
    )
    classification_abs = _validate_existing_file_under_root(
        request["classification"], run_root, ".json", "classification"
    )
    component_manifest_abs = _validate_existing_file_under_root(
        request["component_manifest"], run_root, ".json", "component_manifest"
    )

    canvas_out_abs = _validate_output_path_under_root(
        request["canvas_out"], project_root, ".dart", "canvas_out"
    )
    colors_out_abs = _validate_output_path_under_root(
        request["colors_out"], project_root, ".dart", "colors_out"
    )
    status_bar_out_abs = _validate_output_path_under_root(
        request["status_bar_out"], project_root, ".dart", "status_bar_out"
    )
    implementation_map_out_abs = _validate_output_path_under_root(
        request["implementation_map_out"], run_root, ".json", "implementation_map_out"
    )

    # colors_import_path: project-relative .dart path, must equal colors_out.
    colors_import_path = request["colors_import_path"]
    _check_posix_relative(colors_import_path, "colors_import_path")
    if not colors_import_path.endswith(".dart"):
        raise OperationPlanError(
            f"colors_import_path: must end with .dart: {colors_import_path!r}"
        )
    if colors_import_path != request["colors_out"]:
        raise OperationPlanError(
            "colors_import_path: must equal colors_out: "
            f"{colors_import_path!r} != {request['colors_out']!r}"
        )

    colors_import = _construct_package_import(package_name, colors_import_path)
    asset_prefix = f"assets/icp/{feature_id}"

    return {
        "project_root": project_root,
        "run_root": run_root,
        "render_plan_abs": render_plan_abs,
        "scene_abs": scene_abs,
        "classification_abs": classification_abs,
        "component_manifest_abs": component_manifest_abs,
        "canvas_out_abs": canvas_out_abs,
        "colors_out_abs": colors_out_abs,
        "status_bar_out_abs": status_bar_out_abs,
        "implementation_map_out_abs": implementation_map_out_abs,
        "colors_import": colors_import,
        "asset_prefix": asset_prefix,
        "feature_id": feature_id,
        "canvas_class_name": canvas_class_name,
        "status_bar_class_name": status_bar_class_name,
    }


def _build_visible_steps(
    validated: dict[str, Any], sha_map: dict[str, str]
) -> list[dict[str, Any]]:
    project_root_str = str(validated["project_root"])
    cwd = project_root_str
    steps: list[dict[str, Any]] = []

    # Step 1: generate_canvas (capsule origin).
    spec = _STEP_SPEC_BY_KEY[("flutter.visible_codegen.v1", "generate_canvas")]
    prim = "generate_canvas.py"
    script_path, script_sha = _resolve_script_path_and_sha(spec, prim, sha_map)
    steps.append(
        {
            "step_id": "generate_canvas",
            "primitive": prim,
            "primitive_sha256": script_sha,
            "argv": [
                sys.executable,
                script_path,
                "--render-plan", validated["render_plan_abs"],
                "--out", validated["canvas_out_abs"],
                "--colors-out", validated["colors_out_abs"],
                "--colors-import", validated["colors_import"],
                "--asset-prefix", validated["asset_prefix"],
                "--classification", validated["classification_abs"],
                "--component-manifest", validated["component_manifest_abs"],
                "--class-name", validated["canvas_class_name"],
            ],
            "cwd": cwd,
            "timeout_seconds": TIMEOUT_SECONDS,
        }
    )

    # Step 2: adapt_expected_slots (platform origin). P2.5a2 post-step:
    # reads ONLY the <canvas>.expected.json / <canvas>.slots.json sidecars
    # emitted by step 1, reconstructs the SharedCore projection, proves
    # byte parity, and atomically persists the byte-identical SharedCore
    # output. P2.5b extends the adapter argv with the validated
    # ``--run-root`` and ``--feature-id`` pair so the adapter additionally
    # publishes the canonical projection artifact under
    # ``<run_root>/expected_slots_projections/<feature_id>.json``. Reuses
    # the already-validated project_root, run_root, feature_id, and canvas
    # output.
    spec = _STEP_SPEC_BY_KEY[
        ("flutter.visible_codegen.v1", "adapt_expected_slots")
    ]
    prim = "flutter_expected_slots_adapter_v1.py"
    script_path, script_sha = _resolve_script_path_and_sha(spec, prim, sha_map)
    steps.append(
        {
            "step_id": "adapt_expected_slots",
            "primitive": prim,
            "primitive_sha256": script_sha,
            "argv": [
                sys.executable,
                script_path,
                "--project-root", project_root_str,
                "--canvas", validated["canvas_out_abs"],
                "--run-root", str(validated["run_root"]),
                "--feature-id", validated["feature_id"],
            ],
            "cwd": cwd,
            "timeout_seconds": TIMEOUT_SECONDS,
        }
    )

    # Step 3: make_implementation_map (capsule origin).
    spec = _STEP_SPEC_BY_KEY[
        ("flutter.visible_codegen.v1", "make_implementation_map")
    ]
    prim = "make_implementation_map.py"
    script_path, script_sha = _resolve_script_path_and_sha(spec, prim, sha_map)
    steps.append(
        {
            "step_id": "make_implementation_map",
            "primitive": prim,
            "primitive_sha256": script_sha,
            "argv": [
                sys.executable,
                script_path,
                "--render-plan", validated["render_plan_abs"],
                "--canvas", validated["canvas_out_abs"],
                "--out", validated["implementation_map_out_abs"],
            ],
            "cwd": cwd,
            "timeout_seconds": TIMEOUT_SECONDS,
        }
    )

    # Step 4: make_status_bar_policy (capsule origin).
    spec = _STEP_SPEC_BY_KEY[
        ("flutter.visible_codegen.v1", "make_status_bar_policy")
    ]
    prim = "make_status_bar_policy.py"
    script_path, script_sha = _resolve_script_path_and_sha(spec, prim, sha_map)
    steps.append(
        {
            "step_id": "make_status_bar_policy",
            "primitive": prim,
            "primitive_sha256": script_sha,
            "argv": [
                sys.executable,
                script_path,
                "--scene", validated["scene_abs"],
                "--class-name", validated["status_bar_class_name"],
                "--out", validated["status_bar_out_abs"],
            ],
            "cwd": cwd,
            "timeout_seconds": TIMEOUT_SECONDS,
        }
    )

    return steps


# ---------------------------------------------------------------------------
# fixture_codegen request validation + step building.
# ---------------------------------------------------------------------------


_FIXTURE_REQUEST_KEYS = frozenset(
    {
        "project_root",
        "run_root",
        "package_name",
        "feature_id",
        "slots",
        "projections",
        "out",
    }
)


def _validate_fixture_request(request: dict[str, Any]) -> dict[str, Any]:
    actual = set(request.keys())
    if actual != _FIXTURE_REQUEST_KEYS:
        extra = actual - _FIXTURE_REQUEST_KEYS
        missing = _FIXTURE_REQUEST_KEYS - actual
        raise OperationPlanError(
            f"fixture_codegen request keys mismatch: "
            f"extra={sorted(extra)} missing={sorted(missing)}"
        )

    project_root = _validate_root_path(request["project_root"], "project_root")
    run_root = _validate_root_path(request["run_root"], "run_root")
    _check_root_nesting(project_root, run_root)

    feature_id = _validate_regex(
        request["feature_id"], _PACKAGE_RE, "feature_id"
    )

    slots = request["slots"]
    if not isinstance(slots, dict):
        raise OperationPlanError(
            f"slots: must be a dict, got {type(slots).__name__}"
        )
    if not slots:
        raise OperationPlanError("slots: must be non-empty")
    if len(slots) > _SLOTS_MAX:
        raise OperationPlanError(
            f"slots: too many entries ({len(slots)} > {_SLOTS_MAX})"
        )

    slot_abs: dict[str, str] = {}
    for state_id, rel in slots.items():
        _validate_regex(state_id, _PACKAGE_RE, "slots state id")
        abs_path = _validate_existing_file_under_root(
            rel, run_root, ".json", f"slots[{state_id}]"
        )
        slot_abs[state_id] = abs_path

    # P2.5b: projections is a map state_id -> relative existing .json
    # under run_root. It must have the same unique state-id set as
    # ``slots`` and use the same path rules (1..32 entries, safe state
    # ids, existing relative .json under the validated run root). This
    # is the producer-before-consumer gate: the projection artifacts
    # must already exist (the visible operation's adapt_expected_slots
    # step publishes them) before the fixture operation may build.
    projections = request["projections"]
    if not isinstance(projections, dict):
        raise OperationPlanError(
            f"projections: must be a dict, got {type(projections).__name__}"
        )
    if not projections:
        raise OperationPlanError("projections: must be non-empty")
    if len(projections) > _SLOTS_MAX:
        raise OperationPlanError(
            f"projections: too many entries ({len(projections)} > {_SLOTS_MAX})"
        )
    projection_abs: dict[str, str] = {}
    for state_id, rel in projections.items():
        _validate_regex(state_id, _PACKAGE_RE, "projections state id")
        abs_path = _validate_existing_file_under_root(
            rel, run_root, ".json", f"projections[{state_id}]"
        )
        projection_abs[state_id] = abs_path
    # The projection state-id set must equal the slots state-id set
    # exactly (no missing, no extra, no duplicates — dicts already
    # enforce uniqueness on each side).
    if set(projection_abs.keys()) != set(slot_abs.keys()):
        raise OperationPlanError(
            "projections: state-id set must equal slots state-id set"
        )

    out_abs = _validate_output_path_under_root(
        request["out"], project_root, ".dart", "out"
    )

    return {
        "project_root": project_root,
        "run_root": run_root,
        "feature_id": feature_id,
        "slot_abs": slot_abs,
        "projection_abs": projection_abs,
        "out_abs": out_abs,
    }


def _build_fixture_steps(
    validated: dict[str, Any], sha_map: dict[str, str]
) -> list[dict[str, Any]]:
    cwd = str(validated["project_root"])
    run_root_str = str(validated["run_root"])
    steps: list[dict[str, Any]] = []

    # Step 1: verify_fixture_projections (platform origin). P2.5b
    # read-only guard. Argv is deterministic: interpreter + fixed
    # platform primitive, ``--run-root <abs>``, then all
    # ``--projection STATE=<abs>`` pairs in sorted state order, then all
    # ``--slots STATE=<abs>`` pairs in sorted state order. cwd remains
    # the validated project_root.
    guard_prim = "flutter_fixture_projection_guard_v1.py"
    guard_spec = _STEP_SPEC_BY_KEY[
        ("flutter.fixture_codegen.v1", "verify_fixture_projections")
    ]
    guard_script_path, guard_script_sha = _resolve_script_path_and_sha(
        guard_spec, guard_prim, sha_map
    )
    guard_argv: list[str] = [
        sys.executable,
        guard_script_path,
        "--run-root", run_root_str,
    ]
    for state in sorted(validated["projection_abs"]):
        guard_argv.append("--projection")
        guard_argv.append(
            f"{state}={validated['projection_abs'][state]}"
        )
    for state in sorted(validated["slot_abs"]):
        guard_argv.append("--slots")
        guard_argv.append(f"{state}={validated['slot_abs'][state]}")
    steps.append(
        {
            "step_id": "verify_fixture_projections",
            "primitive": guard_prim,
            "primitive_sha256": guard_script_sha,
            "argv": guard_argv,
            "cwd": cwd,
            "timeout_seconds": TIMEOUT_SECONDS,
        }
    )

    # Step 2: make_visual_fixture (capsule origin). Frozen capsule
    # consumer; argv and cwd remain unchanged.
    prim = "make_visual_fixture.py"
    argv: list[str] = [
        sys.executable,
        str(CAPSULE_SCRIPTS_DIR / prim),
        "--feature", validated["feature_id"],
    ]
    for state in sorted(validated["slot_abs"]):
        argv.append("--slots")
        argv.append(f"{state}={validated['slot_abs'][state]}")
    argv.append("--out")
    argv.append(validated["out_abs"])
    steps.append(
        {
            "step_id": "make_visual_fixture",
            "primitive": prim,
            "primitive_sha256": _lookup_primitive_sha(sha_map, prim),
            "argv": argv,
            "cwd": cwd,
            "timeout_seconds": TIMEOUT_SECONDS,
        }
    )
    return steps


# ---------------------------------------------------------------------------
# trace_harness request validation + step building.
# ---------------------------------------------------------------------------


_TRACE_REQUEST_KEYS = frozenset(
    {
        "project_root",
        "run_root",
        "package_name",
        "page_canvas_expected",
        "page_canvas_projection",
        "shared_components_local",
        "scene",
        "merged_expected_out",
        "provenance_out",
        "page_import_path",
        "page_type",
        "trace_out",
        "responsive_out",
        "responsive_contract_out",
        "viewports_file",
        "safe_area_policy",
        "out",
    }
)

# Fixed artifact basenames that couple merged/provenance/trace outputs.
_MERGED_EXPECTED_BASENAME = "merged_expected.json"
_PROVENANCE_BASENAME = "merged_expected.provenance.json"


def _validate_trace_request(request: dict[str, Any]) -> dict[str, Any]:
    # P2.5d: 17-key schema. The old ambiguous ``expected`` key is gone;
    # the request now carries page_canvas_expected (the legacy file the
    # frozen merge consumes) and page_canvas_projection (the canonical
    # projection the platform gate attests) as DISTINCT identities.
    actual = set(request.keys())
    if actual != _TRACE_REQUEST_KEYS:
        extra = actual - _TRACE_REQUEST_KEYS
        missing = _TRACE_REQUEST_KEYS - actual
        raise OperationPlanError(
            f"trace_harness request keys mismatch: "
            f"extra={sorted(extra)} missing={sorted(missing)}"
        )

    project_root = _validate_root_path(request["project_root"], "project_root")
    run_root = _validate_root_path(request["run_root"], "run_root")
    _check_root_nesting(project_root, run_root)

    package_name = _validate_regex(
        request["package_name"], _PACKAGE_RE, "package_name"
    )

    # Existing inputs under run_root.
    page_canvas_expected_abs = _validate_existing_file_under_root(
        request["page_canvas_expected"], run_root, ".expected.json",
        "page_canvas_expected",
    )
    page_canvas_projection_abs = _validate_existing_file_under_root(
        request["page_canvas_projection"], run_root, ".json",
        "page_canvas_projection",
    )
    scene_abs = _validate_existing_file_under_root(
        request["scene"], run_root, ".json", "scene",
    )
    viewports_file_abs = _validate_existing_file_under_root(
        request["viewports_file"], run_root, ".json", "viewports_file"
    )

    # shared_components_local: required request value, but the safe leaf
    # may be absent (the frozen merge producer handles the missing-local
    # pass-through case via FileNotFoundError -> empty dict). Reuse the
    # output-path-under-root validator so an absent leaf with a safe
    # existing parent is allowed, while any existing leaf must be a
    # non-symlink regular file.
    shared_components_local_abs = _validate_output_path_under_root(
        request["shared_components_local"], run_root, ".json",
        "shared_components_local",
    )

    page_import_path = request["page_import_path"]
    _check_posix_relative(page_import_path, "page_import_path")
    if not page_import_path.endswith(".dart"):
        raise OperationPlanError(
            f"page_import_path: must end with .dart: {page_import_path!r}"
        )
    if not page_import_path.startswith("lib/"):
        raise OperationPlanError(
            f"page_import_path: must begin with lib/: {page_import_path!r}"
        )
    page_import = _construct_package_import(package_name, page_import_path)

    page_type = _validate_regex(
        request["page_type"], _DART_CLASS_RE, "page_type"
    )

    trace_out_abs = _validate_output_path_under_root(
        request["trace_out"], run_root, ".json", "trace_out"
    )
    responsive_out_abs = _validate_output_path_under_root(
        request["responsive_out"], run_root, ".json", "responsive_out"
    )
    responsive_contract_out_abs = _validate_output_path_under_root(
        request["responsive_contract_out"],
        run_root,
        ".json",
        "responsive_contract_out",
    )
    merged_expected_out_abs = _validate_output_path_under_root(
        request["merged_expected_out"], run_root, ".json",
        "merged_expected_out",
    )
    provenance_out_abs = _validate_output_path_under_root(
        request["provenance_out"], run_root, ".json", "provenance_out",
    )

    safe_area_policy = request["safe_area_policy"]
    if not isinstance(safe_area_policy, str):
        raise OperationPlanError(
            f"safe_area_policy: must be a string, got {type(safe_area_policy).__name__}"
        )
    if safe_area_policy not in _SAFE_AREA_ENUMS:
        raise OperationPlanError(
            f"safe_area_policy: must be one of {sorted(_SAFE_AREA_ENUMS)}: "
            f"{safe_area_policy!r}"
        )

    out_abs = _validate_output_path_under_root(
        request["out"], project_root, "_layout_trace_test.dart", "out"
    )

    # Topology + collision invariants. Every identity must be distinct
    # except the intentional cross-step reuse of merged_expected_out
    # (which is the same file written by step 0, attested by step 1,
    # and consumed by step 2).
    if os.path.basename(merged_expected_out_abs) != _MERGED_EXPECTED_BASENAME:
        raise OperationPlanError(
            f"merged_expected_out: basename must be exactly "
            f"{_MERGED_EXPECTED_BASENAME!r}: "
            f"{os.path.basename(merged_expected_out_abs)!r}"
        )
    if os.path.basename(provenance_out_abs) != _PROVENANCE_BASENAME:
        raise OperationPlanError(
            f"provenance_out: basename must be exactly "
            f"{_PROVENANCE_BASENAME!r}: "
            f"{os.path.basename(provenance_out_abs)!r}"
        )
    # merged_expected_out must equal trace_out.parent / merged_expected.json.
    expected_merged_from_trace = os.path.join(
        os.path.dirname(trace_out_abs), _MERGED_EXPECTED_BASENAME,
    )
    if merged_expected_out_abs != expected_merged_from_trace:
        raise OperationPlanError(
            f"merged_expected_out must equal trace_out parent / "
            f"{_MERGED_EXPECTED_BASENAME!r}: "
            f"got {merged_expected_out_abs!r} expected "
            f"{expected_merged_from_trace!r}"
        )
    # provenance_out must equal merged_expected_out parent /
    # merged_expected.provenance.json.
    expected_prov_from_merged = os.path.join(
        os.path.dirname(merged_expected_out_abs), _PROVENANCE_BASENAME,
    )
    if provenance_out_abs != expected_prov_from_merged:
        raise OperationPlanError(
            f"provenance_out must equal merged_expected_out parent / "
            f"{_PROVENANCE_BASENAME!r}: "
            f"got {provenance_out_abs!r} expected "
            f"{expected_prov_from_merged!r}"
        )

    # Identity distinctness: every input and output identity must be
    # distinct except the cross-step reuse of merged_expected_out (which
    # is shared across steps 0, 1, 2 by design). Inputs are read by
    # steps 0 and 1; outputs are produced by step 0 (merged) and step 1
    # (provenance). The consumer step 2 reads merged.
    distinct_identities = {
        page_canvas_expected_abs,
        page_canvas_projection_abs,
        scene_abs,
        viewports_file_abs,
        shared_components_local_abs,
        merged_expected_out_abs,
        provenance_out_abs,
        trace_out_abs,
        responsive_out_abs,
        responsive_contract_out_abs,
        out_abs,
    }
    # page_canvas_expected, page_canvas_projection, scene, local,
    # merged, provenance, trace_out, responsive_out,
    # responsive_contract_out, out => 11 distinct identities.
    if len(distinct_identities) != 11:
        raise OperationPlanError(
            "trace_harness request: input/output identities must be "
            "distinct (only merged_expected_out may be reused across "
            "steps)"
        )

    return {
        "project_root": project_root,
        "run_root": run_root,
        "page_canvas_expected_abs": page_canvas_expected_abs,
        "page_canvas_projection_abs": page_canvas_projection_abs,
        "shared_components_local_abs": shared_components_local_abs,
        "scene_abs": scene_abs,
        "merged_expected_out_abs": merged_expected_out_abs,
        "provenance_out_abs": provenance_out_abs,
        "page_import": page_import,
        "page_type": page_type,
        "trace_out_abs": trace_out_abs,
        "responsive_out_abs": responsive_out_abs,
        "responsive_contract_out_abs": responsive_contract_out_abs,
        "viewports_file_abs": viewports_file_abs,
        "safe_area_policy": safe_area_policy,
        "out_abs": out_abs,
    }


def _build_trace_steps(
    validated: dict[str, Any], sha_map: dict[str, str]
) -> list[dict[str, Any]]:
    cwd = str(validated["project_root"])
    run_root_str = str(validated["run_root"])
    steps: list[dict[str, Any]] = []

    # Step 0: merge_shared_expected (capsule origin). P2.5d frozen
    # producer: consumes the real legacy page .expected.json plus the
    # optional shared_components.local.json + scene.json and produces
    # the canonical merged_expected.json.
    merge_prim = "merge_shared_expected.py"
    merge_spec = _STEP_SPEC_BY_KEY[
        ("flutter.trace_harness.v1", "merge_shared_expected")
    ]
    merge_script_path, merge_script_sha = _resolve_script_path_and_sha(
        merge_spec, merge_prim, sha_map
    )
    steps.append(
        {
            "step_id": "merge_shared_expected",
            "primitive": merge_prim,
            "primitive_sha256": merge_script_sha,
            "argv": [
                sys.executable,
                merge_script_path,
                "--expected", validated["page_canvas_expected_abs"],
                "--local", validated["shared_components_local_abs"],
                "--scene", validated["scene_abs"],
                "--out", validated["merged_expected_out_abs"],
            ],
            "cwd": cwd,
            "timeout_seconds": TIMEOUT_SECONDS,
        }
    )

    # Step 1: verify_merged_expectation_provenance (platform origin).
    # P2.5d single platform-origin gate: proves the P2.5a projection
    # reconstructs the legacy page canvas expected (byte parity),
    # proves the merge output is canonical, attests the actual chain
    # files via the manifest-bound producer SHA, and atomically
    # publishes + re-verifies P2.5c provenance. Cross-step identity:
    # --page-canvas-expected == step 0 --expected; --scene == step 0
    # --scene; --shared-components-local == step 0 --local;
    # --merged-expected == step 0 --out (== step 2 --expected).
    gate_prim = "flutter_merged_expectation_provenance_gate_v1.py"
    gate_spec = _STEP_SPEC_BY_KEY[
        ("flutter.trace_harness.v1", "verify_merged_expectation_provenance")
    ]
    gate_script_path, gate_script_sha = _resolve_script_path_and_sha(
        gate_spec, gate_prim, sha_map
    )
    steps.append(
        {
            "step_id": "verify_merged_expectation_provenance",
            "primitive": gate_prim,
            "primitive_sha256": gate_script_sha,
            "argv": [
                sys.executable,
                gate_script_path,
                "--run-root", run_root_str,
                "--page-canvas-expected", validated["page_canvas_expected_abs"],
                "--page-canvas-projection", validated["page_canvas_projection_abs"],
                "--shared-components-local", validated["shared_components_local_abs"],
                "--scene", validated["scene_abs"],
                "--merged-expected", validated["merged_expected_out_abs"],
                "--provenance-out", validated["provenance_out_abs"],
            ],
            "cwd": cwd,
            "timeout_seconds": TIMEOUT_SECONDS,
        }
    )

    # Step 2: gen_layout_trace_test (capsule origin). P2.5d binds its
    # --expected to the attested merged_expected.json produced by step
    # 0 and attested by step 1, so the consumer's raw-sidecar +
    # adjacent-merged auto-adoption branch is structurally unreachable.
    trace_prim = "gen_layout_trace_test.py"
    trace_spec = _STEP_SPEC_BY_KEY[
        ("flutter.trace_harness.v1", "gen_layout_trace_test")
    ]
    trace_script_path, trace_script_sha = _resolve_script_path_and_sha(
        trace_spec, trace_prim, sha_map
    )
    steps.append(
        {
            "step_id": "gen_layout_trace_test",
            "primitive": trace_prim,
            "primitive_sha256": trace_script_sha,
            "argv": [
                sys.executable,
                trace_script_path,
                "--expected", validated["merged_expected_out_abs"],
                "--page-import", validated["page_import"],
                "--page-type", validated["page_type"],
                "--trace-out", validated["trace_out_abs"],
                "--responsive-out", validated["responsive_out_abs"],
                "--responsive-contract-out", validated["responsive_contract_out_abs"],
                "--viewports-file", validated["viewports_file_abs"],
                "--safe-area-policy", validated["safe_area_policy"],
                "--out", validated["out_abs"],
            ],
            "cwd": cwd,
            "timeout_seconds": TIMEOUT_SECONDS,
        }
    )
    return steps


# ---------------------------------------------------------------------------
# packaging.v1 request validation + step building.
#
# Each request carries common fields plus an ``action`` selector and the
# fields specific to that action. Each action emits exactly one step.
# ---------------------------------------------------------------------------


_PACKAGING_COMMON_KEYS = frozenset({"project_root", "run_root", "package_name", "action"})
_PACKAGING_ACTION_KEYS: dict[str, frozenset[str]] = {
    "copy_assets": frozenset({"asset_manifest_path", "asset_target_path"}),
    "update_pubspec_asset": frozenset({"asset_path"}),
    "prepare": frozenset({"spec_root_path", "packaging_out_path"}),
    "verify": frozenset({"packaging_evidence_path"}),
}


def _validate_packaging_request(request: dict[str, Any]) -> dict[str, Any]:
    actual = set(request.keys())
    # action must be present and one of the known set before we can
    # compute the per-action exact-key set.
    if "action" not in actual:
        raise OperationPlanError(
            "packaging request keys mismatch: missing=['action']"
        )
    action = request["action"]
    if not isinstance(action, str):
        raise OperationPlanError(
            f"action: must be a string, got {type(action).__name__}"
        )
    if action not in _PACKAGING_ACTIONS:
        raise OperationPlanError(
            f"action: must be one of {sorted(_PACKAGING_ACTIONS)}: {action!r}"
        )
    expected_keys = _PACKAGING_COMMON_KEYS | _PACKAGING_ACTION_KEYS[action]
    if actual != expected_keys:
        extra = actual - expected_keys
        missing = expected_keys - actual
        raise OperationPlanError(
            f"packaging[{action}] request keys mismatch: "
            f"extra={sorted(extra)} missing={sorted(missing)}"
        )

    project_root = _validate_root_path(request["project_root"], "project_root")
    run_root = _validate_root_path(request["run_root"], "run_root")
    _check_root_nesting(project_root, run_root)
    package_name = _validate_regex(
        request["package_name"], _PACKAGE_RE, "package_name"
    )

    validated: dict[str, Any] = {
        "project_root": project_root,
        "run_root": run_root,
        "package_name": package_name,
        "action": action,
    }

    if action == "copy_assets":
        manifest_abs = _validate_existing_file_under_root(
            request["asset_manifest_path"], run_root, ".json", "asset_manifest_path"
        )
        target_abs = _validate_target_dir_under_root(
            request["asset_target_path"], project_root, "asset_target_path"
        )
        validated["manifest_abs"] = manifest_abs
        validated["target_abs"] = target_abs
    elif action == "update_pubspec_asset":
        # asset_path must be a canonical project-relative file or dir
        # under the conventional assets/ subtree; pubspec.yaml is never
        # an acceptable asset_path.
        asset_rel = request["asset_path"]
        _check_posix_relative(asset_rel, "asset_path")
        if asset_rel == "pubspec.yaml":
            raise OperationPlanError(
                f"asset_path: must not be pubspec.yaml: {asset_rel!r}"
            )
        _check_subtree_relative(asset_rel, "assets", "asset_path")
        asset_abs = _validate_existing_path_under_root(
            asset_rel, project_root, "asset_path"
        )
        pubspec_abs = _check_project_pubspec(project_root)
        validated["asset_rel"] = asset_rel
        validated["asset_abs"] = asset_abs
        validated["pubspec_abs"] = pubspec_abs
    elif action == "prepare":
        spec_root_abs = _validate_existing_dir_under_root(
            request["spec_root_path"], run_root, "spec_root_path"
        )
        out_abs = _validate_output_path_under_root(
            request["packaging_out_path"], run_root, ".json", "packaging_out_path"
        )
        pubspec_abs = _check_project_pubspec(project_root)
        validated["spec_root_abs"] = spec_root_abs
        validated["out_abs"] = out_abs
        validated["pubspec_abs"] = pubspec_abs
    elif action == "verify":
        evidence_abs = _validate_existing_file_under_root(
            request["packaging_evidence_path"],
            run_root,
            ".json",
            "packaging_evidence_path",
        )
        validated["evidence_abs"] = evidence_abs
    else:  # pragma: no cover - defensive; _PACKAGING_ACTIONS gates this.
        raise OperationPlanError(f"action not buildable: {action!r}")
    return validated


def _build_packaging_steps(
    validated: dict[str, Any], sha_map: dict[str, str]
) -> list[dict[str, Any]]:
    project_root_cwd = str(validated["project_root"])
    action = validated["action"]
    cwd: str
    if action == "copy_assets":
        prim = "copy_assets.py"
        argv = [
            sys.executable,
            str(CAPSULE_SCRIPTS_DIR / prim),
            "--manifest", validated["manifest_abs"],
            "--target", validated["target_abs"],
        ]
        step_id = "copy_assets"
        cwd = project_root_cwd
        timeout = TIMEOUT_SECONDS
    elif action == "update_pubspec_asset":
        prim = "update_pubspec_assets.py"
        argv = [
            sys.executable,
            str(CAPSULE_SCRIPTS_DIR / prim),
            "--pubspec", validated["pubspec_abs"],
            # --asset value is the canonical relative POSIX string.
            "--asset", validated["asset_rel"],
        ]
        step_id = "update_pubspec_asset"
        cwd = project_root_cwd
        timeout = TIMEOUT_SECONDS
    elif action == "prepare":
        prim = "prepare_assembly_packaging.py"
        argv = [
            sys.executable,
            str(CAPSULE_SCRIPTS_DIR / prim),
            "prepare",
            "--spec-root", validated["spec_root_abs"],
            "--project-root", project_root_cwd,
            "--pubspec", validated["pubspec_abs"],
            "--out", validated["out_abs"],
        ]
        step_id = "prepare_assembly_packaging"
        cwd = project_root_cwd
        timeout = TIMEOUT_SECONDS
    elif action == "verify":
        prim = "prepare_assembly_packaging.py"
        # The packaging verify variant is the only P2d2b packaging
        # variant that does NOT bind cwd to project_root: its cwd is
        # the lexical parent directory of the validated ``--evidence``
        # absolute path. This is deterministic from the validated argv
        # value and verify_plan re-attests the exact equality.
        evidence_abs = validated["evidence_abs"]
        argv = [
            sys.executable,
            str(CAPSULE_SCRIPTS_DIR / prim),
            "verify",
            "--evidence", evidence_abs,
        ]
        step_id = "verify_assembly_packaging"
        cwd = str(Path(evidence_abs).parent)
        timeout = TIMEOUT_SECONDS
    else:  # pragma: no cover
        raise OperationPlanError(f"action not buildable: {action!r}")
    return [
        {
            "step_id": step_id,
            "primitive": prim,
            "primitive_sha256": _lookup_primitive_sha(sha_map, prim),
            "argv": argv,
            "cwd": cwd,
            "timeout_seconds": timeout,
        }
    ]


# ---------------------------------------------------------------------------
# test_runner.v1 request validation + step building.
#
# Each request carries common fields plus a ``phase`` selector and the
# fields specific to that phase. Each phase emits exactly one step.
# ---------------------------------------------------------------------------


_TEST_RUNNER_COMMON_KEYS = frozenset(
    {"project_root", "run_root", "package_name", "phase"}
)
_TEST_RUNNER_PHASE_KEYS: dict[str, frozenset[str]] = {
    "red": frozenset({"spec_root_path", "test_target"}),
    "green": frozenset({"spec_root_path", "test_target"}),
    "adopt": frozenset({"spec_root_path", "test_target"}),
    "verify": frozenset({"spec_root_path"}),
    "retire_stale_template_tests": frozenset({"retirement_out_path"}),
}


def _validate_test_runner_request(request: dict[str, Any]) -> dict[str, Any]:
    actual = set(request.keys())
    if "phase" not in actual:
        raise OperationPlanError(
            "test_runner request keys mismatch: missing=['phase']"
        )
    phase = request["phase"]
    if not isinstance(phase, str):
        raise OperationPlanError(
            f"phase: must be a string, got {type(phase).__name__}"
        )
    if phase not in _TEST_RUNNER_PHASES:
        raise OperationPlanError(
            f"phase: must be one of {sorted(_TEST_RUNNER_PHASES)}: {phase!r}"
        )
    expected_keys = _TEST_RUNNER_COMMON_KEYS | _TEST_RUNNER_PHASE_KEYS[phase]
    if actual != expected_keys:
        extra = actual - expected_keys
        missing = expected_keys - actual
        raise OperationPlanError(
            f"test_runner[{phase}] request keys mismatch: "
            f"extra={sorted(extra)} missing={sorted(missing)}"
        )

    project_root = _validate_root_path(request["project_root"], "project_root")
    run_root = _validate_root_path(request["run_root"], "run_root")
    _check_root_nesting(project_root, run_root)
    package_name = _validate_regex(
        request["package_name"], _PACKAGE_RE, "package_name"
    )

    validated: dict[str, Any] = {
        "project_root": project_root,
        "run_root": run_root,
        "package_name": package_name,
        "phase": phase,
    }

    if phase in {"red", "green", "adopt"}:
        spec_root_abs = _validate_existing_dir_under_root(
            request["spec_root_path"], run_root, "spec_root_path"
        )
        # test_target must be a canonical project-relative file or dir
        # strictly below test/; ``test`` itself is rejected.
        test_target_rel = request["test_target"]
        _check_posix_relative(test_target_rel, "test_target")
        _check_subtree_relative(test_target_rel, "test", "test_target")
        test_target_abs = _validate_existing_path_under_root(
            test_target_rel, project_root, "test_target"
        )
        validated["spec_root_abs"] = spec_root_abs
        validated["test_target_rel"] = test_target_rel
        validated["test_target_abs"] = test_target_abs
    elif phase == "verify":
        spec_root_abs = _validate_existing_dir_under_root(
            request["spec_root_path"], run_root, "spec_root_path"
        )
        validated["spec_root_abs"] = spec_root_abs
    elif phase == "retire_stale_template_tests":
        out_abs = _validate_output_path_under_root(
            request["retirement_out_path"],
            run_root,
            ".json",
            "retirement_out_path",
        )
        validated["out_abs"] = out_abs
    else:  # pragma: no cover
        raise OperationPlanError(f"phase not buildable: {phase!r}")
    return validated


def _build_test_runner_steps(
    validated: dict[str, Any], sha_map: dict[str, str]
) -> list[dict[str, Any]]:
    project_root_cwd = str(validated["project_root"])
    phase = validated["phase"]
    cwd: str
    if phase in {"red", "green", "adopt"}:
        prim = "assembly_tdd_guard.py"
        argv = [
            sys.executable,
            str(CAPSULE_SCRIPTS_DIR / prim),
            phase,
            "--spec-root", validated["spec_root_abs"],
            "--project-root", project_root_cwd,
            # --test-target value is the canonical relative POSIX string.
            "--test-target", validated["test_target_rel"],
        ]
        if phase == "red":
            argv.extend(["--failure-kind", _FIXED_FAILURE_KIND])
            step_id = "assembly_tdd_red"
        elif phase == "green":
            step_id = "assembly_tdd_green"
        else:  # adopt
            argv.extend(["--authorization", _FIXED_AUTHORIZATION])
            step_id = "assembly_tdd_adopt"
        cwd = project_root_cwd
        timeout = TIMEOUT_TDD_SECONDS
    elif phase == "verify":
        prim = "assembly_tdd_guard.py"
        # The test_runner verify variant is the only test_runner variant
        # that does NOT bind cwd to project_root: its cwd is the
        # validated absolute ``--spec-root`` path. This is deterministic
        # from the validated argv value and verify_plan re-attests the
        # exact equality.
        spec_root_abs = validated["spec_root_abs"]
        argv = [
            sys.executable,
            str(CAPSULE_SCRIPTS_DIR / prim),
            "verify",
            "--spec-root", spec_root_abs,
        ]
        step_id = "verify_assembly_tdd"
        cwd = spec_root_abs
        timeout = TIMEOUT_SECONDS
    elif phase == "retire_stale_template_tests":
        prim = "retire_stale_flutter_template_tests.py"
        argv = [
            sys.executable,
            str(CAPSULE_SCRIPTS_DIR / prim),
            "--project-root", project_root_cwd,
            "--out", validated["out_abs"],
        ]
        step_id = "retire_stale_template_tests"
        cwd = project_root_cwd
        timeout = TIMEOUT_SECONDS
    else:  # pragma: no cover
        raise OperationPlanError(f"phase not buildable: {phase!r}")
    return [
        {
            "step_id": step_id,
            "primitive": prim,
            "primitive_sha256": _lookup_primitive_sha(sha_map, prim),
            "argv": argv,
            "cwd": cwd,
            "timeout_seconds": timeout,
        }
    ]


# ---------------------------------------------------------------------------
# runtime_capture.v1 request validation + step building.
#
# Each request carries ``project_root``, ``action``, and (for non-lock
# actions) ``spec_root``. The spec artifacts are FIXED basenames under
# spec_root; they are not caller-selectable. The normalized request
# mapping is reconstructed by verify_plan and coupled to request_digest.
# ---------------------------------------------------------------------------


def _validate_runtime_capture_request(request: dict[str, Any]) -> dict[str, Any]:
    actual = set(request.keys())
    if "action" not in actual:
        raise OperationPlanError(
            "runtime_capture request keys mismatch: missing=['action']"
        )
    action = request["action"]
    if not isinstance(action, str):
        raise OperationPlanError(
            f"action: must be a string, got {type(action).__name__}"
        )
    if action not in _RUNTIME_CAPTURE_ACTIONS:
        raise OperationPlanError(
            f"action: must be one of {sorted(_RUNTIME_CAPTURE_ACTIONS)}: {action!r}"
        )
    common = {"project_root", "action"}
    if action in _RUNTIME_CAPTURE_NEEDS_SPEC_ROOT:
        expected_keys = common | {"spec_root"}
    else:
        expected_keys = common
    if actual != expected_keys:
        extra = actual - expected_keys
        missing = expected_keys - actual
        raise OperationPlanError(
            f"runtime_capture[{action}] request keys mismatch: "
            f"extra={sorted(extra)} missing={sorted(missing)}"
        )

    project_root = _validate_root_path(request["project_root"], "project_root")
    validated: dict[str, Any] = {"project_root": project_root, "action": action}

    if action in _RUNTIME_CAPTURE_NEEDS_SPEC_ROOT:
        spec_root = _validate_root_path(request["spec_root"], "spec_root")
        validated["spec_root"] = spec_root

    cwd = str(project_root)
    validated["cwd"] = cwd

    if action == "select_device":
        spec_root = validated["spec_root"]
        out_abs = _check_fixed_spec_output(
            spec_root, "runtime_device.json", "runtime_device.json"
        )
        validated["out_abs"] = out_abs
    elif action == "lock_acquire":
        validated["lock_abs"] = _check_device_lock_path(project_root)
    elif action in ("lock_release", "lock_status"):
        validated["lock_abs"] = _check_device_lock_path(project_root)
    elif action == "capture":
        spec_root = validated["spec_root"]
        validated["selection_abs"] = _check_fixed_spec_input(
            spec_root, "runtime_device.json", "runtime_device.json"
        )
        # out=actual.png and manifest=visual_manifest.json are fixed
        # spec-root OUTPUTS produced by capture; absent is allowed.
        validated["manifest_abs"] = _check_fixed_spec_output(
            spec_root, "visual_manifest.json", "visual_manifest.json"
        )
        validated["out_abs"] = _check_fixed_spec_output(
            spec_root, "actual.png", "actual.png"
        )
    elif action == "physical_preview":
        spec_root = validated["spec_root"]
        validated["out_abs"] = _check_fixed_spec_output(
            spec_root, "physical_device_preview.json",
            "physical_device_preview.json",
        )
    return validated


def _runtime_capture_normalized(validated: dict[str, Any]) -> dict[str, Any]:
    action = validated["action"]
    cwd = validated["cwd"]
    if action in _RUNTIME_CAPTURE_NEEDS_SPEC_ROOT:
        return {
            "action": action,
            "project_root": cwd,
            "spec_root": str(validated["spec_root"]),
        }
    return {"action": action, "project_root": cwd}


def _build_runtime_capture_steps(
    validated: dict[str, Any], sha_map: dict[str, str]
) -> list[dict[str, Any]]:
    cwd = validated["cwd"]
    action = validated["action"]

    if action == "select_device":
        prim = "select_runtime_device.py"
        argv = [
            sys.executable, str(CAPSULE_SCRIPTS_DIR / prim),
            "--platform", "auto",
            "--command-timeout", "10",
            "--boot-timeout", "120",
            "--out", validated["out_abs"],
        ]
        timeout = _TIMEOUT_SELECT_DEVICE
    elif action == "lock_acquire":
        prim = "device_lock.py"
        argv = [
            sys.executable, str(CAPSULE_SCRIPTS_DIR / prim),
            "acquire",
            "--lock", validated["lock_abs"],
            "--timeout", "900",
        ]
        timeout = _TIMEOUT_LOCK_ACQUIRE
    elif action == "lock_release":
        prim = "device_lock.py"
        argv = [
            sys.executable, str(CAPSULE_SCRIPTS_DIR / prim),
            "release",
            "--lock", validated["lock_abs"],
        ]
        timeout = _TIMEOUT_LOCK_RELEASE
    elif action == "lock_status":
        prim = "device_lock.py"
        argv = [
            sys.executable, str(CAPSULE_SCRIPTS_DIR / prim),
            "status",
            "--lock", validated["lock_abs"],
        ]
        timeout = _TIMEOUT_LOCK_STATUS
    elif action == "capture":
        prim = "capture_runtime_screenshot.py"
        argv = [
            sys.executable, str(CAPSULE_SCRIPTS_DIR / prim),
            "--selection", validated["selection_abs"],
            "--command-timeout", "15",
            "--launch-timeout", "300",
            "--out", validated["out_abs"],
            "--manifest", validated["manifest_abs"],
        ]
        timeout = _TIMEOUT_CAPTURE
    elif action == "physical_preview":
        prim = "physical_device_preview.py"
        argv = [
            sys.executable, str(CAPSULE_SCRIPTS_DIR / prim),
            "--project-root", cwd,
            "--out", validated["out_abs"],
        ]
        timeout = _TIMEOUT_PHYSICAL_PREVIEW
    else:  # pragma: no cover
        raise OperationPlanError(f"action not buildable: {action!r}")
    return [
        {
            "step_id": action,
            "primitive": prim,
            "primitive_sha256": _lookup_primitive_sha(sha_map, prim),
            "argv": argv,
            "cwd": cwd,
            "timeout_seconds": timeout,
        }
    ]


# ---------------------------------------------------------------------------
# project_gates.v1 request validation + step building.
# ---------------------------------------------------------------------------


def _validate_project_gates_request(request: dict[str, Any]) -> dict[str, Any]:
    actual = set(request.keys())
    if "action" not in actual:
        raise OperationPlanError(
            "project_gates request keys mismatch: missing=['action']"
        )
    action = request["action"]
    if not isinstance(action, str):
        raise OperationPlanError(
            f"action: must be a string, got {type(action).__name__}"
        )
    if action not in _PROJECT_GATES_ACTIONS:
        raise OperationPlanError(
            f"action: must be one of {sorted(_PROJECT_GATES_ACTIONS)}: {action!r}"
        )
    common = {"project_root", "action"}
    if action in _PROJECT_GATES_NEEDS_SPEC_ROOT:
        expected_keys = common | {"spec_root"}
    else:
        expected_keys = common
    if action == "capture_readiness":
        expected_keys = expected_keys | {
            "page_source", "policy_source", "startup_policy_source"
        }
    if actual != expected_keys:
        extra = actual - expected_keys
        missing = expected_keys - actual
        raise OperationPlanError(
            f"project_gates[{action}] request keys mismatch: "
            f"extra={sorted(extra)} missing={sorted(missing)}"
        )

    project_root = _validate_root_path(request["project_root"], "project_root")
    cwd = str(project_root)
    validated: dict[str, Any] = {"project_root": project_root, "action": action, "cwd": cwd}

    if action == "interaction_wiring":
        spec_root = _validate_root_path(request["spec_root"], "spec_root")
        validated["spec_root"] = spec_root
        validated["lib_abs"] = _check_project_dir(project_root, "lib")
        validated["test_abs"] = _check_project_dir(project_root, "test")
        validated["entry_abs"] = _check_project_entry(project_root)
        validated["pubspec_abs"] = _check_project_pubspec(project_root)
        validated["contract_abs"] = _check_fixed_spec_input(
            spec_root, "interaction_contract.json", "interaction_contract.json"
        )
        validated["out_abs"] = _check_fixed_spec_output(
            spec_root, "wiring_report.json", "wiring_report.json"
        )
    elif action == "api_integration":
        spec_root = _validate_root_path(request["spec_root"], "spec_root")
        validated["spec_root"] = spec_root
        validated["lib_abs"] = _check_project_dir(project_root, "lib")
        validated["api_contract_abs"] = _check_fixed_spec_input(
            spec_root, "api_contract.json", "api_contract.json"
        )
        validated["out_abs"] = _check_fixed_spec_output(
            spec_root, "api_integration_report.json", "api_integration_report.json"
        )
    elif action == "fixture_source":
        # No spec_root; --root is the canonical project_root.
        pass
    elif action == "capture_readiness":
        spec_root = _validate_root_path(request["spec_root"], "spec_root")
        validated["spec_root"] = spec_root
        validated["entry_abs"] = _check_project_entry(project_root)
        validated["scene_abs"] = _check_fixed_spec_input(
            spec_root, "scene.json", "scene.json"
        )
        validated["page_source_abs"] = _validate_abs_existing_file_under_root(
            request["page_source"], project_root, "page_source"
        )
        validated["policy_source_abs"] = _validate_abs_existing_file_under_root(
            request["policy_source"], project_root, "policy_source"
        )
        validated["startup_policy_source_abs"] = _validate_abs_existing_file_under_root(
            request["startup_policy_source"], project_root, "startup_policy_source"
        )
        validated["out_abs"] = _check_fixed_spec_output(
            spec_root, "capture_readiness.json", "capture_readiness.json"
        )
    return validated


def _project_gates_normalized(validated: dict[str, Any]) -> dict[str, Any]:
    action = validated["action"]
    cwd = validated["cwd"]
    if action == "fixture_source":
        return {"action": action, "project_root": cwd}
    if action == "capture_readiness":
        return {
            "action": action,
            "project_root": cwd,
            "spec_root": str(validated["spec_root"]),
            "page_source": validated["page_source_abs"],
            "policy_source": validated["policy_source_abs"],
            "startup_policy_source": validated["startup_policy_source_abs"],
        }
    return {
        "action": action,
        "project_root": cwd,
        "spec_root": str(validated["spec_root"]),
    }


def _build_project_gates_steps(
    validated: dict[str, Any], sha_map: dict[str, str]
) -> list[dict[str, Any]]:
    cwd = validated["cwd"]
    action = validated["action"]

    if action == "interaction_wiring":
        prim = "check_interaction_wiring.py"
        argv = [
            sys.executable, str(CAPSULE_SCRIPTS_DIR / prim),
            "--lib-root", validated["lib_abs"],
            "--test-root", validated["test_abs"],
            "--entry", validated["entry_abs"],
            "--pubspec", validated["pubspec_abs"],
            "--contract", validated["contract_abs"],
            "--out", validated["out_abs"],
        ]
    elif action == "api_integration":
        prim = "check_api_integration.py"
        argv = [
            sys.executable, str(CAPSULE_SCRIPTS_DIR / prim),
            "--api-contract", validated["api_contract_abs"],
            "--lib-root", validated["lib_abs"],
            "--out", validated["out_abs"],
        ]
    elif action == "fixture_source":
        prim = "check_fixture_source.py"
        argv = [
            sys.executable, str(CAPSULE_SCRIPTS_DIR / prim),
            "--root", cwd,
        ]
    elif action == "capture_readiness":
        prim = "check_capture_readiness.py"
        argv = [
            sys.executable, str(CAPSULE_SCRIPTS_DIR / prim),
            "--project-root", cwd,
            "--entry", validated["entry_abs"],
            "--scene", validated["scene_abs"],
            "--page-source", validated["page_source_abs"],
            "--policy-source", validated["policy_source_abs"],
            "--startup-policy-source", validated["startup_policy_source_abs"],
            "--out", validated["out_abs"],
        ]
    else:  # pragma: no cover
        raise OperationPlanError(f"action not buildable: {action!r}")
    return [
        {
            "step_id": action,
            "primitive": prim,
            "primitive_sha256": _lookup_primitive_sha(sha_map, prim),
            "argv": argv,
            "cwd": cwd,
            "timeout_seconds": TIMEOUT_SECONDS,
        }
    ]


# ---------------------------------------------------------------------------
# fan_in.v1 request validation + step building.
# ---------------------------------------------------------------------------


def _validate_fan_in_request(request: dict[str, Any]) -> dict[str, Any]:
    actual = set(request.keys())
    expected_keys = {"project_root", "spec_root", "action"}
    if actual != expected_keys:
        # action-first error message for parity with packaging/test_runner.
        if "action" not in actual:
            raise OperationPlanError(
                "fan_in request keys mismatch: missing=['action']"
            )
        action = request["action"]
        if not isinstance(action, str):
            raise OperationPlanError(
                f"action: must be a string, got {type(action).__name__}"
            )
        if action not in _FAN_IN_ACTIONS:
            raise OperationPlanError(
                f"action: must be one of {sorted(_FAN_IN_ACTIONS)}: {action!r}"
            )
        extra = actual - expected_keys
        missing = expected_keys - actual
        raise OperationPlanError(
            f"fan_in request keys mismatch: "
            f"extra={sorted(extra)} missing={sorted(missing)}"
        )
    action = request["action"]
    if not isinstance(action, str):
        raise OperationPlanError(
            f"action: must be a string, got {type(action).__name__}"
        )
    if action not in _FAN_IN_ACTIONS:
        raise OperationPlanError(
            f"action: must be one of {sorted(_FAN_IN_ACTIONS)}: {action!r}"
        )

    project_root = _validate_root_path(request["project_root"], "project_root")
    spec_root = _validate_root_path(request["spec_root"], "spec_root")
    cwd = str(project_root)
    validated: dict[str, Any] = {
        "project_root": project_root, "spec_root": spec_root,
        "action": action, "cwd": cwd,
    }

    if action == "plan_prepare":
        # assembly_context.json and assembly_decisions.json are fixed
        # spec-root OUTPUTS produced by prepare; absent is allowed.
        validated["context_abs"] = _check_fixed_spec_output(
            spec_root, "assembly_context.json", "assembly_context.json"
        )
        validated["decisions_abs"] = _check_fixed_spec_output(
            spec_root, "assembly_decisions.json", "assembly_decisions.json"
        )
    elif action == "plan_apply":
        # plan_apply READS context/decisions as existing inputs.
        validated["context_abs"] = _check_fixed_spec_input(
            spec_root, "assembly_context.json", "assembly_context.json"
        )
        validated["decisions_abs"] = _check_fixed_spec_input(
            spec_root, "assembly_decisions.json", "assembly_decisions.json"
        )
    elif action in ("supervisor_prepare", "supervisor_verify"):
        validated["contract_abs"] = _check_fixed_spec_input(
            spec_root, "assembly_invocation.json", "assembly_invocation.json"
        )
    elif action == "done_gate":
        validated["out_abs"] = _check_fixed_spec_output(
            spec_root, "done_gate.json", "done_gate.json"
        )
    elif action == "completion_issue":
        validated["evidence_abs"] = _check_fixed_spec_output(
            spec_root, "assembly_completion.json", "assembly_completion.json"
        )
    elif action == "completion_verify":
        validated["evidence_abs"] = _check_fixed_spec_input(
            spec_root, "assembly_completion.json", "assembly_completion.json"
        )
    return validated


def _fan_in_normalized(validated: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": validated["action"],
        "project_root": validated["cwd"],
        "spec_root": str(validated["spec_root"]),
    }


def _build_fan_in_steps(
    validated: dict[str, Any], sha_map: dict[str, str]
) -> list[dict[str, Any]]:
    cwd = validated["cwd"]
    action = validated["action"]
    spec_root_str = str(validated["spec_root"])

    if action == "plan_prepare":
        prim = "assembly_plan_batch.py"
        argv = [
            sys.executable, str(CAPSULE_SCRIPTS_DIR / prim),
            "prepare",
            "--spec-root", spec_root_str,
            "--project-root", cwd,
            "--context", validated["context_abs"],
            "--decisions", validated["decisions_abs"],
        ]
    elif action == "plan_apply":
        prim = "assembly_plan_batch.py"
        argv = [
            sys.executable, str(CAPSULE_SCRIPTS_DIR / prim),
            "apply",
            "--context", validated["context_abs"],
            "--decisions", validated["decisions_abs"],
        ]
    elif action == "supervisor_prepare":
        prim = "assembly_worker_supervisor.py"
        argv = [
            sys.executable, str(CAPSULE_SCRIPTS_DIR / prim),
            "prepare",
            "--contract", validated["contract_abs"],
        ]
    elif action == "supervisor_verify":
        prim = "assembly_worker_supervisor.py"
        argv = [
            sys.executable, str(CAPSULE_SCRIPTS_DIR / prim),
            "verify",
            "--contract", validated["contract_abs"],
        ]
    elif action == "done_gate":
        prim = "check_done_gate.py"
        argv = [
            sys.executable, str(CAPSULE_SCRIPTS_DIR / prim),
            "--spec-root", spec_root_str,
            "--out", validated["out_abs"],
        ]
    elif action == "completion_issue":
        prim = "assembly_completion.py"
        argv = [
            sys.executable, str(CAPSULE_SCRIPTS_DIR / prim),
            "issue",
            "--spec-root", spec_root_str,
            "--evidence", validated["evidence_abs"],
        ]
    elif action == "completion_verify":
        prim = "assembly_completion.py"
        argv = [
            sys.executable, str(CAPSULE_SCRIPTS_DIR / prim),
            "verify",
            "--spec-root", spec_root_str,
            "--evidence", validated["evidence_abs"],
        ]
    else:  # pragma: no cover
        raise OperationPlanError(f"action not buildable: {action!r}")
    return [
        {
            "step_id": action,
            "primitive": prim,
            "primitive_sha256": _lookup_primitive_sha(sha_map, prim),
            "argv": argv,
            "cwd": cwd,
            "timeout_seconds": TIMEOUT_SECONDS,
        }
    ]


# ---------------------------------------------------------------------------
# Plan finalization.
# ---------------------------------------------------------------------------


def _request_digest(request: dict[str, Any]) -> str:
    """SHA-256 of the canonical normalized request bytes."""
    return _sha256_bytes(_canonical_json_bytes(request))


def _build_plan(
    operation_id: str,
    request: dict[str, Any],
    steps: list[dict[str, Any]],
    request_digest: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": KIND_PLAN,
        "schema_version": SCHEMA_VERSION,
        "operation_id": operation_id,
        "platform_id": PLATFORM_ID,
        "profile_id": PROFILE_ID,
        # For the P2d2c operations the digest is computed from the
        # validated normalized request mapping (which verify_plan can
        # reconstruct), not from the raw caller request. For P2d2a/P2d2b
        # the digest remains over the raw normalized request.
        "request_digest": request_digest
        if request_digest is not None
        else _request_digest(request),
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# verify_plan: argv value validators.
# ---------------------------------------------------------------------------


def _check_argv_abs_path(value: str, role: str, flag: str) -> None:
    if not value:
        raise OperationPlanError(f"{role}: {flag} empty path")
    if not os.path.isabs(value):
        raise OperationPlanError(f"{role}: {flag} not absolute: {value!r}")
    if "\\" in value:
        raise OperationPlanError(f"{role}: {flag} contains backslash: {value!r}")
    if "\x00" in value:
        raise OperationPlanError(f"{role}: {flag} contains NUL")
    if os.path.normpath(value) != value:
        raise OperationPlanError(
            f"{role}: {flag} not lexically normalized: {value!r}"
        )
    if any(part == ".." for part in Path(value).parts):
        raise OperationPlanError(f"{role}: {flag} contains '..': {value!r}")


def _validate_argv_value(value: Any, kind: str, role: str, flag: str) -> None:
    if not isinstance(value, str):
        raise OperationPlanError(
            f"{role}: {flag} value not a string: {type(value).__name__}"
        )
    if kind == "abs_path_json":
        _check_argv_abs_path(value, role, flag)
        if not value.endswith(".json"):
            raise OperationPlanError(
                f"{role}: {flag} must end with .json: {value!r}"
            )
    elif kind == "abs_path_dart":
        _check_argv_abs_path(value, role, flag)
        if not value.endswith(".dart"):
            raise OperationPlanError(
                f"{role}: {flag} must end with .dart: {value!r}"
            )
    elif kind == "abs_path_trace_test":
        _check_argv_abs_path(value, role, flag)
        if not value.endswith("_layout_trace_test.dart"):
            raise OperationPlanError(
                f"{role}: {flag} must end with _layout_trace_test.dart: {value!r}"
            )
    elif kind == "dart_class":
        if not _DART_CLASS_RE.match(value):
            raise OperationPlanError(
                f"{role}: {flag} not a Dart class identifier: {value!r}"
            )
    elif kind == "feature_id":
        if not _PACKAGE_RE.match(value):
            raise OperationPlanError(
                f"{role}: {flag} not a valid identifier: {value!r}"
            )
    elif kind == "package_import":
        if not _PACKAGE_IMPORT_RE.match(value):
            raise OperationPlanError(
                f"{role}: {flag} not a valid package import: {value!r}"
            )
    elif kind == "asset_prefix":
        if not _ASSET_PREFIX_RE.match(value):
            raise OperationPlanError(
                f"{role}: {flag} not a valid asset prefix: {value!r}"
            )
    elif kind == "safe_area_enum":
        if value not in _SAFE_AREA_ENUMS:
            raise OperationPlanError(
                f"{role}: {flag} not a valid safe-area policy: {value!r}"
            )
    elif kind == "slots_pair":
        if "=" not in value:
            raise OperationPlanError(
                f"{role}: {flag} not in STATE=ABS form: {value!r}"
            )
        state, abs_path = value.split("=", 1)
        if not _PACKAGE_RE.match(state):
            raise OperationPlanError(
                f"{role}: {flag} state id invalid: {state!r}"
            )
        _check_argv_abs_path(abs_path, role, flag)
        if not abs_path.endswith(".json"):
            raise OperationPlanError(
                f"{role}: {flag} abs path must end with .json: {abs_path!r}"
            )
    elif kind == "projection_pair":
        # P2.5b: same shape as slots_pair (STATE=ABS.json). The
        # projection_pair kind exists separately so verify_plan can
        # independently re-attest the projection flag's sorted/duplicate
        # invariants alongside the slots flag.
        if "=" not in value:
            raise OperationPlanError(
                f"{role}: {flag} not in STATE=ABS form: {value!r}"
            )
        state, abs_path = value.split("=", 1)
        if not _PACKAGE_RE.match(state):
            raise OperationPlanError(
                f"{role}: {flag} state id invalid: {state!r}"
            )
        _check_argv_abs_path(abs_path, role, flag)
        if not abs_path.endswith(".json"):
            raise OperationPlanError(
                f"{role}: {flag} abs path must end with .json: {abs_path!r}"
            )
    elif kind == "abs_path_dir":
        _check_argv_abs_path(value, role, flag)
    elif kind == "abs_path_plain":
        # A plain absolute normalized path with no extension constraint.
        _check_argv_abs_path(value, role, flag)
    elif kind == "abs_path_png":
        _check_argv_abs_path(value, role, flag)
        if not value.endswith(".png"):
            raise OperationPlanError(
                f"{role}: {flag} must end with .png: {value!r}"
            )
    elif kind == "abs_path_yaml":
        _check_argv_abs_path(value, role, flag)
        if not value.endswith(".yaml"):
            raise OperationPlanError(
                f"{role}: {flag} must end with .yaml: {value!r}"
            )
    elif kind == "rel_asset":
        # Relative POSIX path strictly below the conventional assets/
        # subtree. Reject absolute paths, parent traversal, and any
        # non-assets/ prefix.
        if value.startswith("/"):
            raise OperationPlanError(
                f"{role}: {flag} must be relative, got absolute: {value!r}"
            )
        if value == "assets" or not value.startswith("assets/"):
            raise OperationPlanError(
                f"{role}: {flag} must begin with 'assets/': {value!r}"
            )
        # Reuse the canonical posix-relative check for the rest.
        _check_posix_relative(value, f"{role}: {flag}")
    elif kind == "rel_test_target":
        if value.startswith("/"):
            raise OperationPlanError(
                f"{role}: {flag} must be relative, got absolute: {value!r}"
            )
        if value == "test" or not value.startswith("test/"):
            raise OperationPlanError(
                f"{role}: {flag} must begin with 'test/': {value!r}"
            )
        _check_posix_relative(value, f"{role}: {flag}")
    elif kind == "fixed_failure_kind":
        if value != _FIXED_FAILURE_KIND:
            raise OperationPlanError(
                f"{role}: {flag} must be {_FIXED_FAILURE_KIND!r}: {value!r}"
            )
    elif kind == "fixed_authorization":
        if value != _FIXED_AUTHORIZATION:
            raise OperationPlanError(
                f"{role}: {flag} must be {_FIXED_AUTHORIZATION!r}: {value!r}"
            )
    elif kind.startswith("literal:"):
        # A fixed literal token (e.g. "auto", "10"). The expected value
        # is encoded in the kind after the colon so the argv_spec stays a
        # uniform 4-tuple with no extra positional coupling.
        expected = kind[len("literal:"):]
        if value != expected:
            raise OperationPlanError(
                f"{role}: {flag} must be {expected!r}: {value!r}"
            )
    else:
        raise OperationPlanError(
            f"{role}: unknown argv kind {kind!r}"
        )


def _match_argv(
    pairs_args: list[Any], argv_spec: tuple[Any, ...], role: str
) -> list[tuple[str, str]]:
    """Validate the flag/value structure of ``pairs_args`` (argv[2:])
    against ``argv_spec``. Each spec entry is
    ``(flag, value_kind, min_count, max_count)`` where ``max_count`` may
    be ``None`` for repeatable flags.

    Returns the parsed list of ``(flag, value)`` pairs."""
    if len(pairs_args) % 2 != 0:
        raise OperationPlanError(
            f"{role}: odd length (dangling flag): {pairs_args[-1]!r}"
        )
    pairs: list[tuple[str, str]] = []
    for i in range(0, len(pairs_args), 2):
        flag = pairs_args[i]
        value = pairs_args[i + 1]
        if not isinstance(flag, str):
            raise OperationPlanError(f"{role}: flag at {i} not a string")
        pairs.append((flag, value))

    idx = 0
    for spec_flag, kind, min_count, max_count in argv_spec:
        count = 0
        while idx < len(pairs) and pairs[idx][0] == spec_flag:
            _validate_argv_value(pairs[idx][1], kind, role, spec_flag)
            count += 1
            idx += 1
            if max_count is not None and count > max_count:
                raise OperationPlanError(
                    f"{role}: too many {spec_flag!r} ({count} > {max_count})"
                )
        if count < min_count:
            raise OperationPlanError(
                f"{role}: missing {spec_flag!r} (got {count} expected >={min_count})"
            )
    if idx != len(pairs):
        leftover = pairs[idx]
        raise OperationPlanError(
            f"{role}: unexpected trailing flag {leftover[0]!r} at index {idx}"
        )

    # Additional: for repeatable slot flags, verify they are sorted by
    # state id and have no duplicates. This catches tampering that
    # otherwise passes per-value validation.
    slot_specs = [s for s in argv_spec if s[1] == "slots_pair"]
    if slot_specs:
        slot_flag = slot_specs[0][0]
        slot_values = [v for (f, v) in pairs if f == slot_flag]
        states = [v.split("=", 1)[0] for v in slot_values]
        if states != sorted(states):
            raise OperationPlanError(
                f"{role}: {slot_flag} values not sorted by state id"
            )
        if len(set(states)) != len(states):
            raise OperationPlanError(
                f"{role}: {slot_flag} values contain duplicate state ids"
            )
    # P2.5b: same sorted/duplicate-state invariant for the projection
    # flag of the fixture guard step. Independent of the slots check so
    # a tamper that reorders only projections is detected.
    projection_specs = [s for s in argv_spec if s[1] == "projection_pair"]
    if projection_specs:
        projection_flag = projection_specs[0][0]
        projection_values = [v for (f, v) in pairs if f == projection_flag]
        p_states = [v.split("=", 1)[0] for v in projection_values]
        if p_states != sorted(p_states):
            raise OperationPlanError(
                f"{role}: {projection_flag} values not sorted by state id"
            )
        if len(set(p_states)) != len(p_states):
            raise OperationPlanError(
                f"{role}: {projection_flag} values contain duplicate state ids"
            )
    return pairs


# ---------------------------------------------------------------------------
# verify_plan implementation.
# ---------------------------------------------------------------------------


_PLAN_TOP_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "operation_id",
        "platform_id",
        "profile_id",
        "request_digest",
        "steps",
    }
)

_STEP_KEYS = frozenset(
    {
        "step_id",
        "primitive",
        "primitive_sha256",
        "argv",
        "cwd",
        "timeout_seconds",
    }
)


def _extract_single_flag_value(
    pairs_args: list[Any], argv_spec: tuple[Any, ...], flag: str, role: str
) -> str:
    """Return the single validated value associated with ``flag`` in
    ``pairs_args``. ``pairs_args`` is the flag/value list already
    validated by :func:`_match_argv`. The spec must declare ``flag``
    with ``min_count == 1`` and ``max_count == 1``."""
    found: list[str] = []
    spec_entry = None
    for entry in argv_spec:
        if entry[0] == flag:
            spec_entry = entry
            break
    if spec_entry is None:
        raise OperationPlanError(
            f"{role}: flag {flag!r} not declared in argv_spec"
        )
    for j in range(0, len(pairs_args) - 1, 2):
        if pairs_args[j] == flag:
            value = pairs_args[j + 1]
            if not isinstance(value, str):
                raise OperationPlanError(
                    f"{role}: {flag} value not a string"
                )
            found.append(value)
    if len(found) != 1:
        raise OperationPlanError(
            f"{role}: expected exactly one {flag!r}, got {len(found)}"
        )
    return found[0]


def _gv(pairs_args: list[Any], argv_spec: tuple[Any, ...], flag: str) -> str:
    """Shorthand for extracting a single validated flag value from the
    flag/value flat list. Raises on absence or multiplicity."""
    return _extract_single_flag_value(
        pairs_args, argv_spec, flag, "p2d2c reconstruction"
    )


def _basename(value: str) -> str:
    return Path(value).name


def _parent_str(value: str) -> str:
    return str(Path(value).parent)


def _require_basename(value: str, expected: str) -> None:
    if _basename(value) != expected:
        raise OperationPlanError(
            f"fixed artifact basename mismatch: got {_basename(value)!r} "
            f"expected {expected!r}"
        )


def _require_same_parent(values: list[str], role: str) -> str:
    """Require every absolute path in ``values`` to share the same lexical
    parent directory; return that shared parent."""
    parent = _parent_str(values[0])
    for v in values[1:]:
        if _parent_str(v) != parent:
            raise OperationPlanError(
                f"{role}: mixed spec parents: {_parent_str(v)!r} != {parent!r}"
            )
    return parent


def _reconstruct_p2d2c_request(
    operation_id: str,
    step_id: str,
    cwd: str,
    pairs_args: list[Any],
    argv_spec: tuple[Any, ...],
) -> dict[str, Any]:
    """Reconstruct the action's exact normalized request mapping from the
    validated plan values. Performs the fixed-basename and parent-
    consistency checks that couple spec-root derivation to the fixed
    artifact paths. Returns a mapping whose canonical-JSON SHA-256 must
    equal the plan's ``request_digest``.
    """
    action = step_id
    if operation_id == "flutter.runtime_capture.v1":
        if action == "select_device":
            out = _gv(pairs_args, argv_spec, "--out")
            _require_basename(out, "runtime_device.json")
            spec_root = _parent_str(out)
            return {"action": action, "project_root": cwd, "spec_root": spec_root}
        if action in ("lock_acquire", "lock_release", "lock_status"):
            lock = _gv(pairs_args, argv_spec, "--lock")
            expected_lock = os.path.join(cwd, ".icp", "device.lock")
            if lock != expected_lock:
                raise OperationPlanError(
                    f"device lock path mismatch: got {lock!r} "
                    f"expected {expected_lock!r}"
                )
            return {"action": action, "project_root": cwd}
        if action == "capture":
            selection = _gv(pairs_args, argv_spec, "--selection")
            out = _gv(pairs_args, argv_spec, "--out")
            manifest = _gv(pairs_args, argv_spec, "--manifest")
            _require_basename(selection, "runtime_device.json")
            _require_basename(out, "actual.png")
            _require_basename(manifest, "visual_manifest.json")
            spec_root = _require_same_parent(
                [out, selection, manifest], "capture spec artifacts"
            )
            return {"action": action, "project_root": cwd, "spec_root": spec_root}
        if action == "physical_preview":
            out = _gv(pairs_args, argv_spec, "--out")
            projroot = _gv(pairs_args, argv_spec, "--project-root")
            if projroot != cwd:
                raise OperationPlanError(
                    f"physical_preview --project-root must equal cwd: "
                    f"got {projroot!r} expected {cwd!r}"
                )
            _require_basename(out, "physical_device_preview.json")
            spec_root = _parent_str(out)
            return {"action": action, "project_root": cwd, "spec_root": spec_root}
    elif operation_id == "flutter.project_gates.v1":
        if action == "interaction_wiring":
            contract = _gv(pairs_args, argv_spec, "--contract")
            out = _gv(pairs_args, argv_spec, "--out")
            libroot = _gv(pairs_args, argv_spec, "--lib-root")
            testroot = _gv(pairs_args, argv_spec, "--test-root")
            entry = _gv(pairs_args, argv_spec, "--entry")
            pubspec = _gv(pairs_args, argv_spec, "--pubspec")
            for name, val, expected in (
                ("lib-root", libroot, os.path.join(cwd, "lib")),
                ("test-root", testroot, os.path.join(cwd, "test")),
                ("entry", entry, os.path.join(cwd, "lib", "main.dart")),
                ("pubspec", pubspec, os.path.join(cwd, "pubspec.yaml")),
            ):
                if val != expected:
                    raise OperationPlanError(
                        f"project path {name} mismatch: got {val!r} "
                        f"expected {expected!r}"
                    )
            _require_basename(contract, "interaction_contract.json")
            _require_basename(out, "wiring_report.json")
            spec_root = _require_same_parent(
                [contract, out], "interaction_wiring spec artifacts"
            )
            return {"action": action, "project_root": cwd, "spec_root": spec_root}
        if action == "api_integration":
            api_contract = _gv(pairs_args, argv_spec, "--api-contract")
            out = _gv(pairs_args, argv_spec, "--out")
            libroot = _gv(pairs_args, argv_spec, "--lib-root")
            if libroot != os.path.join(cwd, "lib"):
                raise OperationPlanError(
                    f"api_integration --lib-root mismatch: got {libroot!r}"
                )
            _require_basename(api_contract, "api_contract.json")
            _require_basename(out, "api_integration_report.json")
            spec_root = _require_same_parent(
                [api_contract, out], "api_integration spec artifacts"
            )
            return {"action": action, "project_root": cwd, "spec_root": spec_root}
        if action == "fixture_source":
            root = _gv(pairs_args, argv_spec, "--root")
            if root != cwd:
                raise OperationPlanError(
                    f"fixture_source --root must equal cwd: got {root!r}"
                )
            return {"action": action, "project_root": cwd}
        if action == "capture_readiness":
            scene = _gv(pairs_args, argv_spec, "--scene")
            out = _gv(pairs_args, argv_spec, "--out")
            projroot = _gv(pairs_args, argv_spec, "--project-root")
            entry = _gv(pairs_args, argv_spec, "--entry")
            page = _gv(pairs_args, argv_spec, "--page-source")
            policy = _gv(pairs_args, argv_spec, "--policy-source")
            startup = _gv(pairs_args, argv_spec, "--startup-policy-source")
            if projroot != cwd:
                raise OperationPlanError(
                    f"capture_readiness --project-root must equal cwd: "
                    f"got {projroot!r}"
                )
            if entry != os.path.join(cwd, "lib", "main.dart"):
                raise OperationPlanError(
                    f"capture_readiness --entry mismatch: got {entry!r}"
                )
            _require_basename(scene, "scene.json")
            _require_basename(out, "capture_readiness.json")
            spec_root = _require_same_parent(
                [scene, out], "capture_readiness spec artifacts"
            )
            for label, val in (
                ("page_source", page),
                ("policy_source", policy),
                ("startup_policy_source", startup),
            ):
                if not _is_strictly_inside(Path(val), Path(cwd)):
                    raise OperationPlanError(
                        f"{label} not strictly within project_root: {val!r}"
                    )
            return {
                "action": action,
                "project_root": cwd,
                "spec_root": spec_root,
                "page_source": page,
                "policy_source": policy,
                "startup_policy_source": startup,
            }
    elif operation_id == "flutter.fan_in.v1":
        if action == "plan_prepare":
            spec_root = _gv(pairs_args, argv_spec, "--spec-root")
            projroot = _gv(pairs_args, argv_spec, "--project-root")
            context = _gv(pairs_args, argv_spec, "--context")
            decisions = _gv(pairs_args, argv_spec, "--decisions")
            if projroot != cwd:
                raise OperationPlanError(
                    f"plan_prepare --project-root must equal cwd: got {projroot!r}"
                )
            _require_basename(context, "assembly_context.json")
            _require_basename(decisions, "assembly_decisions.json")
            for val, label in ((context, "--context"), (decisions, "--decisions")):
                if _parent_str(val) != spec_root:
                    raise OperationPlanError(
                        f"plan_prepare {label} parent mismatch: "
                        f"{_parent_str(val)!r} != {spec_root!r}"
                    )
            return {"action": action, "project_root": cwd, "spec_root": spec_root}
        if action == "plan_apply":
            context = _gv(pairs_args, argv_spec, "--context")
            decisions = _gv(pairs_args, argv_spec, "--decisions")
            _require_basename(context, "assembly_context.json")
            _require_basename(decisions, "assembly_decisions.json")
            spec_root = _require_same_parent(
                [context, decisions], "plan_apply spec artifacts"
            )
            return {"action": action, "project_root": cwd, "spec_root": spec_root}
        if action in ("supervisor_prepare", "supervisor_verify"):
            contract = _gv(pairs_args, argv_spec, "--contract")
            _require_basename(contract, "assembly_invocation.json")
            spec_root = _parent_str(contract)
            return {"action": action, "project_root": cwd, "spec_root": spec_root}
        if action == "done_gate":
            spec_root = _gv(pairs_args, argv_spec, "--spec-root")
            out = _gv(pairs_args, argv_spec, "--out")
            _require_basename(out, "done_gate.json")
            if _parent_str(out) != spec_root:
                raise OperationPlanError(
                    f"done_gate --out parent mismatch: "
                    f"{_parent_str(out)!r} != {spec_root!r}"
                )
            return {"action": action, "project_root": cwd, "spec_root": spec_root}
        if action in ("completion_issue", "completion_verify"):
            spec_root = _gv(pairs_args, argv_spec, "--spec-root")
            evidence = _gv(pairs_args, argv_spec, "--evidence")
            _require_basename(evidence, "assembly_completion.json")
            if _parent_str(evidence) != spec_root:
                raise OperationPlanError(
                    f"{action} --evidence parent mismatch: "
                    f"{_parent_str(evidence)!r} != {spec_root!r}"
                )
            return {"action": action, "project_root": cwd, "spec_root": spec_root}
    # Any other combination is rejected earlier as an unknown variant.
    raise OperationPlanError(  # pragma: no cover - _STEP_SPEC_BY_KEY gates this.
        f"cannot reconstruct p2d2c request for ({operation_id!r}, {step_id!r})"
    )


def _verify_trace_cross_step_identity(steps: list[dict[str, Any]]) -> None:
    """P2.5d: re-attest the trace_harness cross-step identity and
    topology relationships from the validated plan's argv values.

    Called by :func:`_verify_plan_impl` after per-step argv validation
    has run. Reconstructs the canonical absolute path strings from the
    validated flat argv pairs (flag, value) and requires the exact
    equalities:

      * step[0].argv ``--expected``        == step[1].argv ``--page-canvas-expected``
      * step[0].argv ``--local``           == step[1].argv ``--shared-components-local``
      * step[0].argv ``--scene``           == step[1].argv ``--scene``
      * step[0].argv ``--out``             == step[1].argv ``--merged-expected``
                                            == step[2].argv ``--expected``

    plus the fixed output topology:

      * step[1].argv ``--merged-expected`` basename is exactly
        ``merged_expected.json``;
      * step[1].argv ``--provenance-out`` basename is exactly
        ``merged_expected.provenance.json`` and shares its parent dir
        with ``--merged-expected``;
      * step[1].argv ``--merged-expected``'s parent equals
        step[2].argv ``--trace-out``'s parent.

    Each ``--flag`` is required to appear exactly once in its step's
    argv; per-step argv validation already enforced value shape.
    """
    if len(steps) != 3:
        raise OperationPlanError(
            "trace_harness cross-step identity requires exactly 3 steps"
        )
    # Build a per-step single-flag lookup over the validated flat argv.
    def _flag_value(step: dict[str, Any], flag: str, step_idx: int) -> str:
        argv = step["argv"]
        # argv[0] = interpreter, argv[1] = script, then flag/value pairs.
        pairs = argv[2:]
        found: list[str] = []
        for j in range(0, len(pairs) - 1, 2):
            if pairs[j] == flag:
                v = pairs[j + 1]
                if not isinstance(v, str):
                    raise OperationPlanError(
                        f"step[{step_idx}] {flag}: value not a string"
                    )
                found.append(v)
        if len(found) != 1:
            raise OperationPlanError(
                f"step[{step_idx}] {flag}: expected exactly 1 occurrence, "
                f"got {len(found)}"
            )
        return found[0]

    s0 = steps[0]
    s1 = steps[1]
    s2 = steps[2]
    s0_expected = _flag_value(s0, "--expected", 0)
    s0_local = _flag_value(s0, "--local", 0)
    s0_scene = _flag_value(s0, "--scene", 0)
    s0_out = _flag_value(s0, "--out", 0)
    s1_pce = _flag_value(s1, "--page-canvas-expected", 1)
    s1_local = _flag_value(s1, "--shared-components-local", 1)
    s1_scene = _flag_value(s1, "--scene", 1)
    s1_merged = _flag_value(s1, "--merged-expected", 1)
    s1_prov = _flag_value(s1, "--provenance-out", 1)
    s2_expected = _flag_value(s2, "--expected", 2)
    s2_trace_out = _flag_value(s2, "--trace-out", 2)

    if s0_expected != s1_pce:
        raise OperationPlanError(
            "trace cross-step identity: step[0] --expected != step[1] "
            "--page-canvas-expected"
        )
    if s0_local != s1_local:
        raise OperationPlanError(
            "trace cross-step identity: step[0] --local != step[1] "
            "--shared-components-local"
        )
    if s0_scene != s1_scene:
        raise OperationPlanError(
            "trace cross-step identity: step[0] --scene != step[1] --scene"
        )
    if s0_out != s1_merged:
        raise OperationPlanError(
            "trace cross-step identity: step[0] --out != step[1] "
            "--merged-expected"
        )
    if s0_out != s2_expected:
        raise OperationPlanError(
            "trace cross-step identity: step[0] --out != step[2] --expected"
        )
    if s1_merged != s2_expected:
        raise OperationPlanError(
            "trace cross-step identity: step[1] --merged-expected != "
            "step[2] --expected"
        )
    # Topology.
    if os.path.basename(s1_merged) != _MERGED_EXPECTED_BASENAME:
        raise OperationPlanError(
            f"trace topology: step[1] --merged-expected basename must be "
            f"{_MERGED_EXPECTED_BASENAME!r}"
        )
    if os.path.basename(s1_prov) != _PROVENANCE_BASENAME:
        raise OperationPlanError(
            f"trace topology: step[1] --provenance-out basename must be "
            f"{_PROVENANCE_BASENAME!r}"
        )
    if os.path.dirname(s1_merged) != os.path.dirname(s1_prov):
        raise OperationPlanError(
            "trace topology: step[1] --merged-expected and "
            "--provenance-out must share a parent directory"
        )
    if os.path.dirname(s1_merged) != os.path.dirname(s2_trace_out):
        raise OperationPlanError(
            "trace topology: step[1] --merged-expected parent must equal "
            "step[2] --trace-out parent"
        )


def _verify_plan_impl(plan: dict[str, Any]) -> dict[str, Any]:
    # 1. Capsule + manifest binding.
    _verify_capsule()
    manifest = _load_manifest()
    sha_map = _manifest_sha_map(manifest)

    # 2. Top-level shape.
    if not isinstance(plan, dict):
        raise OperationPlanError("plan must be a dict")
    # The explicit top-level keys-set check is the authority here: it
    # rejects ANY unknown top-level field, which is a strict superset of
    # the forbidden executable-injection fields (command/shell/env/
    # prompt/executable/...). A recursive forbidden-key walk is NOT
    # applied to the plan because the plan schema legitimately carries
    # ``operation_id`` and per-step ``argv`` fields.
    if set(plan.keys()) != _PLAN_TOP_KEYS:
        extra = set(plan.keys()) - _PLAN_TOP_KEYS
        missing = _PLAN_TOP_KEYS - set(plan.keys())
        raise OperationPlanError(
            f"plan top-level keys mismatch: "
            f"extra={sorted(extra)} missing={sorted(missing)}"
        )
    if plan["kind"] != KIND_PLAN:
        raise OperationPlanError(f"plan kind mismatch: {plan['kind']!r}")
    if plan["schema_version"] != SCHEMA_VERSION:
        raise OperationPlanError(
            f"plan schema_version mismatch: {plan['schema_version']!r}"
        )
    if plan["platform_id"] != PLATFORM_ID:
        raise OperationPlanError(
            f"plan platform_id mismatch: {plan['platform_id']!r}"
        )
    if plan["profile_id"] != PROFILE_ID:
        raise OperationPlanError(
            f"plan profile_id mismatch: {plan['profile_id']!r}"
        )
    operation_id = plan["operation_id"]
    if not isinstance(operation_id, str):
        raise OperationPlanError("plan operation_id not a string")
    if operation_id not in _OPERATION_IDS:
        raise OperationPlanError(
            f"plan operation_id unknown: {operation_id!r}"
        )
    if not _is_sha256_hex(plan["request_digest"]):
        raise OperationPlanError("plan request_digest malformed")

    # 3. Steps.
    steps = plan["steps"]
    if not isinstance(steps, list):
        raise OperationPlanError("plan steps not a list")
    # Determine the canonical step count and per-step spec lookup rule
    # for this operation. Fixed-order operations (visible/fixture/trace)
    # carry an ordered tuple of step specs; single-step variant
    # operations (packaging/test_runner) carry exactly one step whose
    # step_id is one of the allowed variant set.
    if operation_id in _OPERATION_STEPS:
        steps_spec = _OPERATION_STEPS[operation_id]
        if len(steps) != len(steps_spec):
            raise OperationPlanError(
                f"plan steps count mismatch: got {len(steps)} "
                f"expected {len(steps_spec)}"
            )
        is_variant = False
    else:
        # Single-step variant operation: exactly one step whose step_id
        # belongs to the operation's allowed variant set.
        if operation_id not in _SINGLE_STEP_VARIANTS:
            raise OperationPlanError(
                f"plan operation_id has no step spec: {operation_id!r}"
            )
        if len(steps) != 1:
            raise OperationPlanError(
                f"plan steps count mismatch: got {len(steps)} "
                f"expected 1 (single-step variant)"
            )
        is_variant = True
        steps_spec = None

    seen_primitives: set[str] = set()
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise OperationPlanError(f"step[{i}] not an object")
        # The explicit step keys-set check is the authority: it rejects
        # ANY unknown step field, including any executable-injection
        # field (command/shell/env/prompt/executable/...). A recursive
        # forbidden-key walk is NOT applied because the step schema
        # legitimately carries ``argv``.
        if set(step.keys()) != _STEP_KEYS:
            extra = set(step.keys()) - _STEP_KEYS
            missing = _STEP_KEYS - set(step.keys())
            raise OperationPlanError(
                f"step[{i}] keys mismatch: "
                f"extra={sorted(extra)} missing={sorted(missing)}"
            )
        # Infer the exact known variant from (operation_id, step_id).
        # This is the single source of truth for the per-step spec.
        step_id = step["step_id"]
        if not isinstance(step_id, str):
            raise OperationPlanError(f"step[{i}] step_id not a string")
        spec_key = (operation_id, step_id)
        if spec_key not in _STEP_SPEC_BY_KEY:
            raise OperationPlanError(
                f"step[{i}] unknown variant ({operation_id!r}, {step_id!r})"
            )
        spec = _STEP_SPEC_BY_KEY[spec_key]
        if not is_variant:
            # Fixed-order operation: also enforce that the step_id
            # matches the spec at this exact position.
            expected_step_id = steps_spec[i]["step_id"]
            if step_id != expected_step_id:
                raise OperationPlanError(
                    f"step[{i}] step_id mismatch: got {step_id!r} "
                    f"expected {expected_step_id!r}"
                )
        else:
            # Single-step variant: step_id must be in the allowed set
            # (already enforced by _STEP_SPEC_BY_KEY lookup above).
            pass
        primitive = step["primitive"]
        if not isinstance(primitive, str):
            raise OperationPlanError(f"step[{i}] primitive not a string")
        if primitive != spec["primitive"]:
            raise OperationPlanError(
                f"step[{i}] primitive mismatch: got {primitive!r} "
                f"expected {spec['primitive']!r}"
            )
        if not _is_safe_basename(primitive):
            raise OperationPlanError(
                f"step[{i}] primitive not a safe basename: {primitive!r}"
            )
        if primitive in seen_primitives:
            raise OperationPlanError(
                f"duplicate primitive ownership: {primitive!r}"
            )
        seen_primitives.add(primitive)
        # Origin-aware SHA binding. The origin is recovered from the fixed
        # internal step spec (never from the plan or request). Capsule
        # primitives must be present in the frozen vendor manifest;
        # platform primitives must NOT collide with any capsule-manifest
        # basename and their SHA-256 is recomputed from the regular
        # non-symlink file under PLATFORM_SCRIPTS_DIR.
        origin = spec.get("script_origin", _ORIGIN_CAPSULE)
        if origin not in _CLOSED_ORIGINS:
            raise OperationPlanError(
                f"step[{i}] unknown script_origin {origin!r}"
            )
        if origin == _ORIGIN_CAPSULE:
            if primitive not in sha_map:
                raise OperationPlanError(
                    f"step[{i}] primitive {primitive!r} not in manifest"
                )
            expected_sha = sha_map[primitive]
        else:  # _ORIGIN_PLATFORM
            if primitive in sha_map:
                raise OperationPlanError(
                    f"step[{i}] platform primitive {primitive!r} "
                    f"collides with capsule manifest"
                )
            expected_sha = _lookup_platform_script_sha(primitive, sha_map)
        sha = step["primitive_sha256"]
        if not _is_sha256_hex(sha):
            raise OperationPlanError(
                f"step[{i}] primitive_sha256 malformed: {sha!r}"
            )
        if sha != expected_sha:
            raise OperationPlanError(
                f"step[{i}] primitive_sha256 mismatch for {primitive!r}"
            )

        # argv structure: fixed interpreter, fixed script (capsule or
        # platform per the closed origin), fixed positional subcommand
        # (when present), then fixed flag/value template.
        argv = step["argv"]
        if not isinstance(argv, list):
            raise OperationPlanError(f"step[{i}] argv not a list")
        if len(argv) < 2:
            raise OperationPlanError(f"step[{i}] argv too short")
        if not isinstance(argv[0], str):
            raise OperationPlanError(f"step[{i}] argv[0] not a string")
        if argv[0] != sys.executable:
            raise OperationPlanError(
                f"step[{i}] argv[0] not fixed interpreter (sys.executable)"
            )
        if origin == _ORIGIN_CAPSULE:
            expected_script = str(CAPSULE_SCRIPTS_DIR / primitive)
            script_role = "capsule script"
        else:  # _ORIGIN_PLATFORM
            expected_script = str(PLATFORM_SCRIPTS_DIR / primitive)
            script_role = "platform script"
        if not isinstance(argv[1], str):
            raise OperationPlanError(f"step[{i}] argv[1] not a string")
        if argv[1] != expected_script:
            raise OperationPlanError(
                f"step[{i}] argv[1] not fixed {script_role}: "
                f"got {argv[1]!r} expected {expected_script!r}"
            )
        # The fixed positional subcommand (e.g. ``prepare``/``verify``/
        # ``red``/``green``/...) when the primitive uses argparse
        # subparsers. Must match the spec exactly.
        argv_rest = argv[2:]
        positional = spec.get("positional")
        if positional is not None:
            if not argv_rest:
                raise OperationPlanError(
                    f"step[{i}] argv missing positional subcommand "
                    f"{positional!r}"
                )
            if not isinstance(argv_rest[0], str):
                raise OperationPlanError(
                    f"step[{i}] argv positional not a string"
                )
            if argv_rest[0] != positional:
                raise OperationPlanError(
                    f"step[{i}] argv positional mismatch: "
                    f"got {argv_rest[0]!r} expected {positional!r}"
                )
            pairs_args = argv_rest[1:]
        else:
            pairs_args = argv_rest
        _match_argv(pairs_args, spec["argv_spec"], f"step[{i}] argv")

        # cwd structure: absolute normalized path string. The exact
        # relationship between cwd and the validated argv path values
        # is determined by the variant's cwd_binding rule. This is how
        # verify_plan independently detects a tampered cwd: the plan
        # carries no separate project_root field, so cwd must be
        # reproducible from the validated argv path values themselves.
        cwd = step["cwd"]
        if not isinstance(cwd, str):
            raise OperationPlanError(f"step[{i}] cwd not a string")
        if not os.path.isabs(cwd):
            raise OperationPlanError(f"step[{i}] cwd not absolute")
        if os.path.normpath(cwd) != cwd:
            raise OperationPlanError(f"step[{i}] cwd not lexically normalized")
        if any(part == ".." for part in Path(cwd).parts):
            raise OperationPlanError(f"step[{i}] cwd contains '..'")
        cwd_binding = spec.get("cwd_binding", _CWD_PROJECT_ROOT_OR_DESCENDANT)
        cwd_path = Path(cwd)
        if cwd_binding == _CWD_PROJECT_ROOT_OR_DESCENDANT:
            # Re-walk pairs_args (already validated by _match_argv) as
            # flag/value pairs and require at least one absolute path
            # value to be either exactly equal to cwd or a strict
            # descendant of cwd. Equality covers variants whose only
            # project-rooted argv value is ``--project-root <cwd>``
            # itself (e.g. test_runner red/green/adopt, retire).
            found_cwd_anchor = False
            for j in range(0, len(pairs_args) - 1, 2):
                value = pairs_args[j + 1]
                if isinstance(value, str) and os.path.isabs(value):
                    value_path = Path(value)
                    if value_path == cwd_path or _is_strictly_inside(
                        value_path, cwd_path
                    ):
                        found_cwd_anchor = True
                        break
            if not found_cwd_anchor:
                raise OperationPlanError(
                    f"step[{i}] cwd has no project-rooted argv path: "
                    f"cwd={cwd!r}"
                )
        elif cwd_binding == _CWD_EVIDENCE_PARENT:
            # packaging verify: cwd must equal the lexical parent
            # directory of the validated ``--evidence`` argv value.
            evidence_value = _extract_single_flag_value(
                pairs_args, spec["argv_spec"], "--evidence", f"step[{i}] argv"
            )
            expected_cwd = str(Path(evidence_value).parent)
            if cwd != expected_cwd:
                raise OperationPlanError(
                    f"step[{i}] cwd must equal evidence parent: "
                    f"cwd={cwd!r} expected={expected_cwd!r}"
                )
        elif cwd_binding == _CWD_SPEC_ROOT:
            # test_runner verify: cwd must equal the validated
            # ``--spec-root`` argv value.
            spec_root_value = _extract_single_flag_value(
                pairs_args, spec["argv_spec"], "--spec-root", f"step[{i}] argv"
            )
            if cwd != spec_root_value:
                raise OperationPlanError(
                    f"step[{i}] cwd must equal spec-root: "
                    f"cwd={cwd!r} expected={spec_root_value!r}"
                )
        elif cwd_binding == _CWD_DIGEST_COUPLING:
            # P2d2c variants: cwd is the canonical project_root but the
            # argv may contain only spec-root paths (select_device,
            # capture). The cwd relationship to the rest of the plan is
            # proven by the normalized-request digest coupling below,
            # which reconstructs the per-action normalized request from
            # cwd + validated argv values and requires exact equality
            # with request_digest. No argv-path anchor is required here.
            pass
        elif cwd_binding == _CWD_PROJECT_ROOT_WITH_RUN_ROOT:
            # P2.5b fixture projection guard: cwd is the validated
            # project_root, but the guard argv carries only --run-root
            # plus projection/slots paths under run_root (none of which
            # directly anchor cwd when run_root is disjoint from
            # project_root). Merely re-applying _check_root_nesting
            # accepts any arbitrary tampered cwd that is disjoint from
            # run_root, so the guard cwd provenance is closed by
            # requiring it to equal the immediately-following consumer
            # step's cwd. The consumer (make_visual_fixture) is itself
            # independently anchored to its project-rooted --out argv
            # path by the default cwd_binding, so this equality closes
            # the guard cwd provenance gap without adding --project-root
            # to the guard CLI or changing the accepted guard argv
            # contract.
            #
            # The next step must exist, be the fixed consumer
            # (make_visual_fixture), and have a cwd equal to this step's
            # cwd. run-root nesting is retained as defense in depth.
            if i + 1 >= len(steps):
                raise OperationPlanError(
                    f"step[{i}] cwd_binding "
                    f"{_CWD_PROJECT_ROOT_WITH_RUN_ROOT!r} requires a "
                    f"following consumer step"
                )
            next_step = steps[i + 1]
            if not isinstance(next_step, dict):
                raise OperationPlanError(
                    f"step[{i + 1}] not an object"
                )
            next_step_id = next_step.get("step_id")
            if next_step_id != "make_visual_fixture":
                raise OperationPlanError(
                    f"step[{i}] cwd_binding requires next step to be "
                    f"make_visual_fixture, got {next_step_id!r}"
                )
            next_cwd = next_step.get("cwd")
            if not isinstance(next_cwd, str):
                raise OperationPlanError(
                    f"step[{i + 1}] cwd not a string"
                )
            if cwd != next_cwd:
                raise OperationPlanError(
                    f"step[{i}] cwd must equal following consumer cwd: "
                    f"cwd={cwd!r} next={next_cwd!r}"
                )
            # Defense in depth: re-attest the cwd<->run_root nesting
            # relationship via the --run-root argv value.
            run_root_value = _extract_single_flag_value(
                pairs_args, spec["argv_spec"], "--run-root",
                f"step[{i}] argv",
            )
            try:
                _check_root_nesting(cwd_path, Path(run_root_value))
            except OperationPlanError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise OperationPlanError(
                    f"step[{i}] cwd/run_root nesting check raised "
                    f"{type(exc).__name__}"
                ) from exc
        elif cwd_binding == _CWD_TRACE_HARNESS_CHAIN:
            # P2.5d trace_harness chain binding. Steps 0 (merge) and 1
            # (gate) carry only run-root-anchored argv paths. Their cwd
            # provenance is closed by requiring this step's cwd to equal
            # the immediately-following step's cwd. The chain terminates
            # at step 2 (gen_layout_trace_test), whose default
            # _CWD_PROJECT_ROOT_OR_DESCENDANT binding independently
            # anchors cwd to project_root via its --out argv value.
            # Transitive equality therefore proves step 0 cwd == step 1
            # cwd == step 2 cwd == project_root.
            if i + 1 >= len(steps):
                raise OperationPlanError(
                    f"step[{i}] cwd_binding "
                    f"{_CWD_TRACE_HARNESS_CHAIN!r} requires a following "
                    f"consumer step"
                )
            next_step = steps[i + 1]
            if not isinstance(next_step, dict):
                raise OperationPlanError(
                    f"step[{i + 1}] not an object"
                )
            next_cwd = next_step.get("cwd")
            if not isinstance(next_cwd, str):
                raise OperationPlanError(
                    f"step[{i + 1}] cwd not a string"
                )
            if cwd != next_cwd:
                raise OperationPlanError(
                    f"step[{i}] cwd must equal following consumer cwd: "
                    f"cwd={cwd!r} next={next_cwd!r}"
                )
            # Defense in depth: if this step's argv carries --run-root
            # (only the gate step does), re-attest cwd<->run_root
            # nesting. The merge step has no --run-root; its run_root
            # identity is recovered transitively from the gate step
            # via the cross-step identity check that runs after all
            # steps are validated.
            try:
                run_root_value = _extract_single_flag_value(
                    pairs_args, spec["argv_spec"], "--run-root",
                    f"step[{i}] argv",
                )
            except OperationPlanError:
                run_root_value = None
            if run_root_value is not None:
                try:
                    _check_root_nesting(cwd_path, Path(run_root_value))
                except OperationPlanError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    raise OperationPlanError(
                        f"step[{i}] cwd/run_root nesting check raised "
                        f"{type(exc).__name__}"
                    ) from exc
        else:  # pragma: no cover - defensive; enum is closed.
            raise OperationPlanError(
                f"step[{i}] unknown cwd_binding {cwd_binding!r}"
            )

        # timeout is fixed per variant. P2d2c variants carry an explicit
        # ``timeout`` in their step spec; P2d2a/P2d2b keep the legacy
        # computation.
        if "timeout" in spec:
            expected_timeout = spec["timeout"]
        else:
            expected_timeout = TIMEOUT_TDD_SECONDS if (
                operation_id == "flutter.test_runner.v1"
                and step_id in {
                    "assembly_tdd_red",
                    "assembly_tdd_green",
                    "assembly_tdd_adopt",
                }
            ) else TIMEOUT_SECONDS
        if step["timeout_seconds"] != expected_timeout:
            raise OperationPlanError(
                f"step[{i}] timeout_seconds mismatch: "
                f"got {step['timeout_seconds']!r} "
                f"expected {expected_timeout}"
            )

        # P2d2c normalized-request digest coupling. For these operations
        # the plan carries no separate project_root field, so the action's
        # exact normalized request is reconstructed from (operation_id,
        # step_id), cwd, and the validated argv values, then canonical-
        # JSON hashed and compared to request_digest. This detects a
        # cwd-only substitution even when argv contains only spec-root
        # paths, and any argv-path-only substitution (via fixed-basename
        # checks plus the digest coupling). A fully coordinated
        # unauthenticated rewrite of every plan value plus a freshly
        # recomputed digest is outside what static verification can
        # distinguish from a different valid caller request; P2e must
        # bind the accepted plan/digest to the current preflight and
        # frozen inputs before execution.
        if operation_id in _P2D2C_OPERATIONS:
            normalized = _reconstruct_p2d2c_request(
                operation_id, step_id, cwd, pairs_args, spec["argv_spec"]
            )
            reconstructed_digest = _sha256_bytes(
                _canonical_json_bytes(normalized)
            )
            if reconstructed_digest != plan["request_digest"]:
                raise OperationPlanError(
                    f"step[{i}] request_digest mismatch: normalized "
                    f"request coupling broken"
                )

    # P2.5d: trace_harness cross-step identity coupling. For a plan
    # supplied directly to verify_plan (not only one built by build()),
    # reconstruct and re-attest the cross-step identity relationships:
    #   * step 0 --expected == step 1 --page-canvas-expected
    #   * step 0 --local     == step 1 --shared-components-local
    #   * step 0 --scene     == step 1 --scene
    #   * step 0 --out       == step 1 --merged-expected
    #                        == step 2 --expected
    # plus the fixed output topology:
    #   * step 1 --merged-expected's basename is exactly merged_expected.json
    #   * step 1 --provenance-out's basename is exactly
    #     merged_expected.provenance.json and shares its parent dir with
    #     step 1 --merged-expected
    #   * step 1 --merged-expected's parent equals step 2 --trace-out's
    #     parent
    # Every value compared as a canonical absolute string.
    if operation_id == "flutter.trace_harness.v1":
        _verify_trace_cross_step_identity(steps)

    # 4. Compute plan digest.
    plan_bytes = _canonical_json_bytes(plan)
    plan_digest = _sha256_bytes(plan_bytes)
    return {
        "ok": True,
        "kind": KIND_VERIFY,
        "schema_version": SCHEMA_VERSION,
        "operation_id": operation_id,
        "steps_total": len(steps),
        "plan_digest": plan_digest,
    }


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def list_operation_ids() -> tuple[str, ...]:
    """Return the fixed, ordered tuple of the legacy-backed Flutter argv
    operation IDs built by this registry.

    A fresh tuple is returned on each call (via unpacking into a new
    tuple literal) so callers cannot mutate the module-level constant
    and so the returned object is never the constant itself. (CPython
    optimizes ``tuple(t)`` and ``t[:]`` to return ``t`` itself for
    tuples; unpacking defeats that optimization.)
    """
    return (*_OPERATION_IDS,)


def build(operation_id: str, request: dict[str, Any]) -> dict[str, Any]:
    """Verify the installed capsule, strict-load the fixed manifest,
    validate the exact request schema for ``operation_id``, build the
    canonical plan, call :func:`verify_plan` on it, and return the plan.

    Generic failures surface as :class:`OperationPlanError` carrying the
    original exception's type name only; arbitrary exception text is
    never leaked.
    """
    try:
        # 1. Capsule verification first, before any request inspection.
        _verify_capsule()
        # 2. Strict-load the fixed manifest with duplicate-key rejection.
        manifest = _load_manifest()
        sha_map = _manifest_sha_map(manifest)
        # 3. Validate operation_id is one of the registered operations.
        if not isinstance(operation_id, str):
            raise OperationPlanError(
                f"operation_id: must be a string, got {type(operation_id).__name__}"
            )
        if operation_id not in _OPERATION_IDS:
            raise OperationPlanError(
                f"unknown operation_id: {operation_id!r}"
            )
        # 4. Validate request is a dict.
        if not isinstance(request, dict):
            raise OperationPlanError(
                f"request: must be a dict, got {type(request).__name__}"
            )
        # 5. Reject forbidden keys recursively in caller data.
        _reject_forbidden_keys(request, "request")
        # 6. Dispatch to the operation-specific validator + builder.
        if operation_id == "flutter.visible_codegen.v1":
            validated = _validate_visible_request(request)
            steps = _build_visible_steps(validated, sha_map)
        elif operation_id == "flutter.fixture_codegen.v1":
            validated = _validate_fixture_request(request)
            steps = _build_fixture_steps(validated, sha_map)
        elif operation_id == "flutter.trace_harness.v1":
            validated = _validate_trace_request(request)
            steps = _build_trace_steps(validated, sha_map)
        elif operation_id == "flutter.packaging.v1":
            validated = _validate_packaging_request(request)
            steps = _build_packaging_steps(validated, sha_map)
        elif operation_id == "flutter.test_runner.v1":
            validated = _validate_test_runner_request(request)
            steps = _build_test_runner_steps(validated, sha_map)
        elif operation_id == "flutter.runtime_capture.v1":
            validated = _validate_runtime_capture_request(request)
            steps = _build_runtime_capture_steps(validated, sha_map)
            normalized_request = _runtime_capture_normalized(validated)
        elif operation_id == "flutter.project_gates.v1":
            validated = _validate_project_gates_request(request)
            steps = _build_project_gates_steps(validated, sha_map)
            normalized_request = _project_gates_normalized(validated)
        elif operation_id == "flutter.fan_in.v1":
            validated = _validate_fan_in_request(request)
            steps = _build_fan_in_steps(validated, sha_map)
            normalized_request = _fan_in_normalized(validated)
        else:  # pragma: no cover - defensive; _OPERATION_IDS gates this.
            raise OperationPlanError(
                f"operation_id not buildable: {operation_id!r}"
            )
        # 7. Build the canonical plan. For the P2d2c operations the digest
        # is over the validated normalized request mapping (which
        # verify_plan reconstructs); for P2d2a/P2d2b it stays over the raw
        # normalized request.
        if operation_id in _P2D2C_OPERATIONS:
            plan = _build_plan(
                operation_id, request, steps,
                request_digest=_request_digest(normalized_request),
            )
        else:
            plan = _build_plan(operation_id, request, steps)
        # 8. Verify the plan before returning. Call the public
        # ``verify_plan`` so the full verification pipeline (including
        # its own generic-exception redaction) runs exactly as an
        # external caller would experience it.
        verify_plan(plan)
        # 9. Return.
        return plan
    except OperationPlanError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise OperationPlanError(
            f"build raised {type(exc).__name__}"
        ) from exc


def verify_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Independently re-verify a trusted-operation plan.

    Re-verifies the capsule/manifest binding, the exact top-level and
    step keys, operation id, step count/order, primitive ownership, the
    fixed interpreter/script/positional/cwd/timeout, and the full argv
    flag/value structure (including request-derived argv positions,
    which must pass their strict type/path/value validators). For
    single-step variant operations (packaging/test_runner) the exact
    variant is inferred from ``(operation_id, step_id)`` and any other
    combination is rejected. Rejects any command/shell/env/prompt or
    unknown executable field anywhere.

    Without the original normalized request, this proves
    schema/invariants/manifest binding and request-derived value
    shapes, not equality to an unavailable original request.

    Returns a verification report of kind
    ``icp.trusted-operation-plan-verify.v1``. Generic failures surface as
    :class:`OperationPlanError` carrying the original exception's type
    name only.
    """
    try:
        return _verify_plan_impl(plan)
    except OperationPlanError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise OperationPlanError(
            f"verify_plan raised {type(exc).__name__}"
        ) from exc
