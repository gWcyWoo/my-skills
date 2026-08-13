#!/usr/bin/env python3
"""Deterministic public-CLI selftest for transitive Apifox ref-resource caching."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


CACHE_CLI = Path(__file__).with_name("oas_ref_resource_cache.py")


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CACHE_CLI), *args],
        text=True,
        capture_output=True,
    )


def main() -> int:
    encoded_lower = "%e9%80%9a%e7%94%a8%e8%bf%94%e5%9b%9e%e6%a0%bc%e5%bc%8f"
    encoded_upper = "%E9%80%9A%E7%94%A8%E8%BF%94%E5%9B%9E%E6%A0%BC%E5%BC%8F"
    unicode_path = f"/components/schemas/{encoded_upper}.json"
    id_name_path = "/components/schemas/id-name%20object.json"

    with tempfile.TemporaryDirectory(prefix="iff-oas-ref-cache-selftest-") as raw_tmp:
        tmp = Path(raw_tmp)
        oas_path = tmp / "oas.json"
        resources_path = tmp / "oas_ref_resources.json"
        missing_path = tmp / "oas_missing_ref_paths.json"
        incoming_path = tmp / "oas_ref_resources.next.json"

        write_json(
            oas_path,
            {
                "openapi": "3.0.0",
                "paths": {"/auth/logOff": {"$ref": "/paths/_auth_logOff.json"}},
                "components": {"schemas": {"$ref": "/components/schemas/index.json"}},
            },
        )
        write_json(
            resources_path,
            {
                "/components/schemas/index.json": json.dumps(
                    {
                        "unicodeRelative": {
                            "$ref": f"./{encoded_lower}.json#/properties/data"
                        },
                        "unicodeAbsoluteDuplicate": {"$ref": unicode_path},
                        "idName": {"$ref": "./id-name%20object.json"},
                        "fragmentOnly": {"$ref": "#/definitions/local"},
                    },
                    ensure_ascii=False,
                ),
                "/paths/_auth_logOff.json": json.dumps(
                    {
                        "post": {
                            "responses": {
                                "200": {
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "$ref": "../components/schemas/id-name%20object.json#/properties/data"
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
            },
        )

        completed = run_cli(
            "missing",
            "--oas",
            str(oas_path),
            "--ref-resources",
            str(resources_path),
            "--out",
            str(missing_path),
        )
        if completed.returncode != 0:
            raise AssertionError(f"missing command failed: {completed.stderr or completed.stdout}")
        assert json.loads(missing_path.read_text(encoding="utf-8")) == [
            unicode_path,
            id_name_path,
        ]

        base_before = resources_path.read_text(encoding="utf-8")
        write_json(incoming_path, {})
        completed = run_cli(
            "merge",
            "--base",
            str(resources_path),
            "--incoming",
            str(incoming_path),
            "--required",
            str(missing_path),
            "--out",
            str(resources_path),
        )
        assert completed.returncode != 0, "no-progress merge unexpectedly succeeded"
        assert "no progress" in completed.stderr, completed.stderr
        assert resources_path.read_text(encoding="utf-8") == base_before

        write_json(incoming_path, {"/components/schemas/unrelated.json": "{}"})
        completed = run_cli(
            "merge",
            "--base",
            str(resources_path),
            "--incoming",
            str(incoming_path),
            "--required",
            str(missing_path),
            "--out",
            str(resources_path),
        )
        assert completed.returncode != 0, "merge that repeats required missing refs unexpectedly succeeded"
        assert "required ref resources not returned" in completed.stderr, completed.stderr
        assert resources_path.read_text(encoding="utf-8") == base_before

        write_json(
            incoming_path,
            {
                "/components/schemas/通用返回格式.json": json.dumps(
                    {"type": "object", "properties": {"code": {"type": "integer"}}},
                    ensure_ascii=False,
                ),
                id_name_path: json.dumps(
                    {"type": "object", "properties": {"id": {"type": "integer"}}},
                    ensure_ascii=False,
                ),
            },
        )
        completed = run_cli(
            "merge",
            "--base",
            str(resources_path),
            "--incoming",
            str(incoming_path),
            "--required",
            str(missing_path),
            "--out",
            str(resources_path),
        )
        if completed.returncode != 0:
            raise AssertionError(f"merge command failed: {completed.stderr or completed.stdout}")
        merged = json.loads(resources_path.read_text(encoding="utf-8"))
        assert list(merged) == sorted(merged), list(merged)
        assert unicode_path in merged

        completed = run_cli(
            "missing",
            "--oas",
            str(oas_path),
            "--ref-resources",
            str(resources_path),
            "--out",
            str(missing_path),
        )
        if completed.returncode != 0:
            raise AssertionError(f"second missing command failed: {completed.stderr or completed.stdout}")
        assert json.loads(missing_path.read_text(encoding="utf-8")) == []

    print("ok oas ref resource cache")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
