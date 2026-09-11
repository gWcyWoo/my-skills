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
USUALLY_INTERACTIVE_ROLES = {"navigation", "list", "modal"}
VALID_IX_TYPES = {"behavior", "data"}
VALID_ROLES = {"navigation", "header", "form", "list", "modal", "footer", "action", "content", "decoration"}
VALID_RESPONSE_LEAF_TYPES = {"string", "integer", "number", "boolean"}
VALID_METHODS = {"GET", "POST"}
VALID_AUTH_VALUES = {"public", "bearer", "optional"}
_ROLE_PRIORITY = {**{r: 1 for r in USUALLY_INTERACTIVE_ROLES}, **{r: 2 for r in INTERACTIVE_ROLES}}


def _project_root(binding_path: str) -> Path:
    # binding lives at {project}/.codex/icp/{title}/component-binding.json
    return Path(binding_path).resolve().parents[3]


def cmd_check_binding(args):
    spec = json.loads(Path(args.component_spec).read_text(encoding="utf-8"))
    binding = json.loads(Path(args.binding).read_text(encoding="utf-8"))
    root = _project_root(args.binding)

    spec_names = {c["name"] for c in spec.get("components", [])}
    components = binding.get("components", [])
    bound_names = {c.get("group_name") for c in components}

    errors = []
    warnings = []

    for g in sorted(spec_names - bound_names):
        errors.append({"type": "unbound_group", "group_name": g})

    for g in sorted(bound_names - spec_names - {None}):
        warnings.append({"type": "extra_group", "group_name": g})

    cn_types = {}
    for comp in components:
        gn = comp.get("group_name", "")
        cn = comp.get("component_name", "")
        ct = comp.get("component_type", "")
        sp = comp.get("source_path")
        params = comp.get("params", [])
        affected = comp.get("affected")

        if not cn:
            errors.append({"type": "missing_component_name", "group_name": gn})

        if ct not in VALID_TYPES:
            errors.append({"type": "invalid_type", "group_name": gn, "component_type": ct})
            continue

        if cn and cn in cn_types and cn_types[cn] != ct:
            errors.append({"type": "inconsistent_type", "component_name": cn,
                           "types": sorted({cn_types[cn], ct})})
        if cn:
            cn_types[cn] = ct

        if ct == "existing_shared":
            if not sp:
                errors.append({"type": "missing_source", "group_name": gn, "component_name": cn})
            elif not (root / sp).exists():
                errors.append({"type": "missing_source", "group_name": gn, "source_path": sp})

        if sp and ct != "existing_shared":
            warnings.append({"type": "unexpected_source_path", "group_name": gn, "component_name": cn, "component_type": ct})

        if affected and ct != "extract_shared":
            errors.append({"type": "invalid_affected", "group_name": gn, "component_type": ct})

        if ct == "extract_shared" and not affected:
            warnings.append({"type": "extract_shared_no_affected", "group_name": gn, "component_name": cn})

        if ct == "extract_shared" and affected:
            if not isinstance(affected, list):
                errors.append({"type": "invalid_affected", "group_name": gn,
                               "detail": "affected 必须是数组"})
            else:
                for a in affected:
                    if not isinstance(a, dict):
                        errors.append({"type": "invalid_affected_entry", "group_name": gn,
                                       "detail": "affected 元素必须是 {name, source_path} 对象"})
                        continue
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

    comp_names = {c.get("component_name") for c in binding.get("components", [])} - {None}
    api_endpoints = {a.get("semantic_hint") or a.get("endpoint")
                     for a in binding.get("apis") or [] if isinstance(a, dict)}
    interactions = binding.get("interactions") or []

    comp_roles = {}
    spec = json.loads(Path(args.component_spec).read_text(encoding="utf-8"))
    group_roles = {g["name"]: g.get("role", "") for g in spec.get("components", [])}
    for c in binding.get("components", []):
        gn = c.get("group_name", "")
        cn = c.get("component_name", "")
        role = group_roles.get(gn, "")
        if cn not in comp_roles or _ROLE_PRIORITY.get(role, 0) > _ROLE_PRIORITY.get(comp_roles[cn], 0):
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

        for f in ("trigger", "behavior", "result", "type"):
            if not ix.get(f):
                errors.append({"type": "incomplete_interaction", "id": ix_id, "missing_field": f})
        if "state" in ix and ix["state"] is not None and not ix["state"]:
            errors.append({"type": "incomplete_interaction", "id": ix_id, "missing_field": "state"})

        ix_type = ix.get("type")
        if ix_type and ix_type not in VALID_IX_TYPES:
            errors.append({"type": "invalid_interaction_type", "id": ix_id, "interaction_type": ix_type})

        if ix_type == "data":
            if not ix.get("api"):
                errors.append({"type": "missing_api", "id": ix_id})
            if "state" not in ix or ix["state"] is None:
                warnings.append({"type": "data_without_state", "id": ix_id})

        api_ref = ix.get("api")
        if api_ref and api_ref not in api_endpoints:
            errors.append({"type": "unknown_api", "id": ix_id, "api": api_ref})

        for tid in ix.get("triggers") or []:
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
        elif role in USUALLY_INTERACTIVE_ROLES or role not in VALID_ROLES:
            warnings.append({"type": "idle_component", "component_name": cn, "role": role})

    # --- resolved 格式校验 ---
    for api in binding.get("apis") or []:
        if not isinstance(api, dict):
            errors.append({"type": "invalid_api_entry",
                           "detail": "apis 元素必须是对象"})
            continue
        hint = api.get("semantic_hint") or api.get("endpoint") or "?"
        resolved = api.get("resolved")
        if resolved is None:
            continue
        if not isinstance(resolved, dict):
            errors.append({"type": "invalid_resolved", "api": hint,
                           "detail": "resolved 必须是 object 或 null"})
            continue
        if not resolved.get("path"):
            errors.append({"type": "missing_resolved_field", "api": hint, "field": "path"})
        method = resolved.get("method")
        if not method:
            errors.append({"type": "missing_resolved_field", "api": hint, "field": "method"})
        elif method not in VALID_METHODS:
            errors.append({"type": "invalid_method", "api": hint, "method": method,
                           "allowed": sorted(VALID_METHODS)})
        auth = resolved.get("auth")
        if auth is not None and auth not in VALID_AUTH_VALUES:
            errors.append({"type": "invalid_auth", "api": hint, "auth": auth,
                           "allowed": sorted(VALID_AUTH_VALUES)})
        if resolved.get("deprecated"):
            warnings.append({"type": "deprecated_api", "api": hint})
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
    p_ix.add_argument("--component-spec", required=True, help="Stage 1 输出 JSON")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    cmds = {"check-binding": cmd_check_binding, "check-interactions": cmd_check_interactions}
    return cmds[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
