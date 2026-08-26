#!/usr/bin/env python3
"""ICP Stage 2 — validate: 验证组件绑定和交互拆解的结构正确性。

两个子命令:
  check-binding       验证组件绑定完整性和约束
  check-interactions  验证原子交互结构和引用正确性
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

VALID_TYPES = {"existing_shared", "extract_shared", "platform_builtin", "new"}
SHARED_TYPES = {"existing_shared", "extract_shared"}
INTERACTIVE_ROLES = {"action", "form"}
VALID_RESPONSE_LEAF_TYPES = {"string", "integer", "number", "boolean"}
VALID_AUTH_VALUES = {"public", "bearer", "optional"}


def _project_root(binding_path: str) -> Path:
    # binding lives at {project}/.codex/icp/{title}/component-binding.json
    return Path(binding_path).resolve().parents[3]


def cmd_check_binding(args):
    spec = json.loads(Path(args.component_spec).read_text(encoding="utf-8"))
    binding = json.loads(Path(args.binding).read_text(encoding="utf-8"))
    root = _project_root(args.binding)

    spec_names = {c["name"] for c in spec.get("components", spec.get("groups", []))}
    components = binding.get("components", [])
    bound_names = {c.get("group_name") for c in components}

    errors = []
    warnings = []

    for g in sorted(spec_names - bound_names):
        errors.append({"type": "unbound_group", "group_name": g})

    for g in sorted(bound_names - spec_names - {None}):
        warnings.append({"type": "extra_group", "group_name": g})

    for comp in components:
        gn = comp.get("group_name", "")
        cn = comp.get("component_name", "")
        ct = comp.get("component_type", "")
        sp = comp.get("source_path")
        params = comp.get("params", [])
        affected = comp.get("affected")

        if ct not in VALID_TYPES:
            errors.append({"type": "invalid_type", "group_name": gn, "component_type": ct})
            continue

        if ct == "existing_shared":
            if not sp:
                errors.append({"type": "missing_source", "group_name": gn, "component_name": cn})
            elif not (root / sp).exists():
                errors.append({"type": "missing_source", "group_name": gn, "source_path": sp})

        if affected and ct != "extract_shared":
            errors.append({"type": "invalid_affected", "group_name": gn, "component_type": ct})

        if ct == "extract_shared" and affected:
            for a in affected:
                asp = a.get("source_path", "")
                if not asp or not (root / asp).exists():
                    errors.append({
                        "type": "missing_affected_source",
                        "group_name": gn,
                        "affected_name": a.get("name", ""),
                        "source_path": asp,
                    })

        if ct in SHARED_TYPES and not params:
            errors.append({"type": "empty_params", "group_name": gn, "component_name": cn})

        if ct == "platform_builtin":
            r = subprocess.run(
                ["grep", "-rl", "--exclude-dir=.git", "--exclude-dir=build",
                 "--exclude-dir=.gradle", "--exclude-dir=node_modules",
                 "--exclude-dir=.codex", "--exclude-dir=.claude",
                 "--exclude-dir=.dart_tool",
                 cn, str(root)],
                capture_output=True, text=True,
            )
            if not r.stdout.strip():
                warnings.append({"type": "unverified_builtin", "group_name": gn, "component_name": cn})

    ok = len(errors) == 0
    result = {"ok": ok}
    if errors:
        result["errors"] = errors
    if warnings:
        result["warnings"] = warnings
    print(json.dumps(result, ensure_ascii=False))
    return 0 if ok else 1


def cmd_check_interactions(args):
    binding = json.loads(Path(args.binding).read_text(encoding="utf-8"))

    comp_names = {c.get("component_name") for c in binding.get("components", [])}
    api_endpoints = {a.get("semantic_hint") or a.get("endpoint") for a in binding.get("apis", [])}
    interactions = binding.get("interactions", [])

    comp_roles = {}
    if args.component_spec:
        spec = json.loads(Path(args.component_spec).read_text(encoding="utf-8"))
        group_roles = {g["name"]: g.get("role", "") for g in spec.get("components", spec.get("groups", []))}
        for c in binding.get("components", []):
            gn = c.get("group_name", "")
            cn = c.get("component_name", "")
            role = group_roles.get(gn, "")
            if cn not in comp_roles or role in INTERACTIVE_ROLES:
                comp_roles[cn] = role

    errors = []
    warnings = []
    comps_with_ix = set()

    ix_ids = set()
    for i, ix in enumerate(interactions):
        ix_id = ix.get("id")
        if not ix_id:
            errors.append({"type": "missing_id", "index": i})
        elif ix_id in ix_ids:
            errors.append({"type": "duplicate_id", "id": ix_id})
        else:
            ix_ids.add(ix_id)

    for i, ix in enumerate(interactions):
        ix_id = ix.get("id") or f"?_{i}"

        for f in ("trigger", "behavior", "result"):
            if not ix.get(f):
                errors.append({"type": "incomplete_interaction", "id": ix_id, "missing_field": f})
        if "state" in ix and ix["state"] is not None and not ix["state"]:
            errors.append({"type": "incomplete_interaction", "id": ix_id, "missing_field": "state"})

        if ix.get("type") == "data" and not ix.get("api"):
            errors.append({"type": "missing_api", "id": ix_id})

        api_ref = ix.get("api")
        if api_ref and api_ref not in api_endpoints:
            errors.append({"type": "unknown_api", "id": ix_id, "api": api_ref})

        for tid in ix.get("triggers", []):
            if tid not in ix_ids:
                errors.append({"type": "broken_trigger", "id": ix_id, "target": tid})


        comp = ix.get("component")
        if comp:
            if comp not in comp_names:
                errors.append({"type": "unknown_component", "id": ix_id, "component": comp})
            comps_with_ix.add(comp)
        else:
            errors.append({"type": "incomplete_interaction", "id": ix_id, "missing_field": "component"})

    for cn in sorted(comp_names - comps_with_ix):
        role = comp_roles.get(cn, "")
        if role in INTERACTIVE_ROLES:
            errors.append({"type": "idle_interactive_component", "component_name": cn, "role": role})
        elif not role:
            warnings.append({"type": "idle_component", "component_name": cn})

    # --- resolved 格式校验 ---
    for api in binding.get("apis", []):
        hint = api.get("semantic_hint") or api.get("endpoint") or "?"
        resolved = api.get("resolved")
        if resolved is None:
            continue
        auth = resolved.get("auth")
        if auth is not None and auth not in VALID_AUTH_VALUES:
            errors.append({"type": "invalid_auth", "api": hint, "auth": auth,
                           "allowed": sorted(VALID_AUTH_VALUES)})
        resp = resolved.get("response")
        if resp is not None:
            if not isinstance(resp, dict):
                errors.append({"type": "invalid_response_schema", "api": hint,
                               "detail": "resolved.response 必须是 object 或 null"})
            else:
                bad = _check_response_schema(resp, hint)
                errors.extend(bad)

    ok = len(errors) == 0
    result = {"ok": ok}
    if errors:
        result["errors"] = errors
    if warnings:
        result["warnings"] = warnings
    print(json.dumps(result, ensure_ascii=False))
    return 0 if ok else 1


def _check_response_schema(obj, api_hint, path=""):
    """递归校验 resolved.response 只含合法类型。"""
    errors = []
    for key, val in obj.items():
        field_path = f"{path}.{key}" if path else key
        if isinstance(val, str):
            if val not in VALID_RESPONSE_LEAF_TYPES:
                errors.append({"type": "invalid_response_schema", "api": api_hint,
                               "field": field_path, "value": val,
                               "detail": f"叶子值必须是 {sorted(VALID_RESPONSE_LEAF_TYPES)} 之一"})
        elif isinstance(val, dict):
            errors.extend(_check_response_schema(val, api_hint, field_path))
        elif isinstance(val, list):
            if len(val) != 1 or not isinstance(val[0], dict):
                errors.append({"type": "invalid_response_schema", "api": api_hint,
                               "field": field_path,
                               "detail": "数组必须写成 [{...}] 形式(恰好一个对象元素描述 item schema)"})
            else:
                errors.extend(_check_response_schema(val[0], api_hint, f"{field_path}[]"))
        else:
            errors.append({"type": "invalid_response_schema", "api": api_hint,
                           "field": field_path,
                           "detail": f"不支持的类型 {type(val).__name__}"})
    return errors


def main():
    parser = argparse.ArgumentParser(description="ICP Stage 2 validate")
    sub = parser.add_subparsers(dest="command")

    p_bind = sub.add_parser("check-binding", help="验证组件绑定")
    p_bind.add_argument("--component-spec", required=True, help="Stage 1 输出 JSON")
    p_bind.add_argument("--binding", required=True, help="组件绑定 JSON")

    p_ix = sub.add_parser("check-interactions", help="验证原子交互")
    p_ix.add_argument("--binding", required=True, help="完整绑定 JSON")
    p_ix.add_argument("--component-spec", default=None, help="Stage 1 输出 JSON(可选,用于按 role 区分 idle 严重级别)")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    cmds = {"check-binding": cmd_check_binding, "check-interactions": cmd_check_interactions}
    return cmds[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
