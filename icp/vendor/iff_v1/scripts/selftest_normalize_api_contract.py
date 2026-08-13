#!/usr/bin/env python3
"""Deterministic CLI selftest for Apifox external OAS references."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


NORMALIZER = Path(__file__).with_name("normalize_api_contract.py")


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_normalizer(root: Path, resources: Path, out: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(NORMALIZER),
            "--oas",
            str(root),
            "--ref-resources",
            str(resources),
            "--out",
            str(out),
        ],
        text=True,
        capture_output=True,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="iff-oas-refs-selftest-") as raw_tmp:
        tmp = Path(raw_tmp)
        root_path = tmp / "oas.json"
        resources_path = tmp / "oas_ref_resources.json"
        out_path = tmp / "api_contract.json"

        write_json(
            root_path,
            {
                "openapi": "3.0.0",
                "paths": {
                    "/home/products": {"$ref": "/paths/_home_products.json"},
                },
            },
        )
        write_json(
            resources_path,
            {
                "/paths/_home_products.json": {
                    "get": {
                        "summary": "Home products",
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "/components/schemas/Envelope.json"}
                                    }
                                }
                            }
                        },
                    }
                },
                "/components/schemas/Envelope.json": {
                    "type": "object",
                    "properties": {
                        "data": {"$ref": "./Product.json"},
                    },
                },
                "/components/schemas/Product.json": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "price": {"type": "number", "nullable": True},
                    },
                },
            },
        )

        completed = run_normalizer(root_path, resources_path, out_path)
        if completed.returncode != 0:
            raise AssertionError(f"nested refs failed: {completed.stderr or completed.stdout}")
        contract = json.loads(out_path.read_text(encoding="utf-8"))
        fields = contract["endpoints"]["/home/products"]["GET"]["responseFields"]
        assert fields["data"]["fields"]["name"]["type"] == "string", fields
        assert fields["data"]["fields"]["price"]["nullable"] is True, fields

        write_json(
            root_path,
            {
                "openapi": "3.0.0",
                "paths": {
                    "/auth/logOff": {"$ref": "/paths/_auth_logOff.json"},
                },
                "components": {
                    "schemas": {"$ref": "/components/schemas/index.json"},
                },
            },
        )
        encoded_schema_path = (
            "/components/schemas/"
            "%E9%80%9A%E7%94%A8%E8%BF%94%E5%9B%9E%E6%A0%BC%E5%BC%8F.json"
        )
        path_resource = {
            "post": {
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/%E9%80%9A%E7%94%A8%E8%BF%94%E5%9B%9E%E6%A0%BC%E5%BC%8F"
                                }
                            }
                        }
                    }
                }
            }
        }
        schema_index = {
            "通用返回格式": {"$ref": encoded_schema_path},
        }
        write_json(
            resources_path,
            {
                "/paths/_auth_logOff.json": json.dumps(path_resource, ensure_ascii=False),
                "/components/schemas/index.json": json.dumps(schema_index, ensure_ascii=False),
            },
        )
        completed = run_normalizer(root_path, resources_path, out_path)
        assert completed.returncode != 0, "incomplete detached resource bundle unexpectedly succeeded"
        assert f"missing external ref resource: {encoded_schema_path}" in completed.stderr, completed.stderr

        write_json(
            resources_path,
            {
                "/paths/_auth_logOff.json": json.dumps(path_resource, ensure_ascii=False),
                "/components/schemas/index.json": json.dumps(schema_index, ensure_ascii=False),
                encoded_schema_path: json.dumps(
                    {
                        "type": "object",
                        "properties": {
                            "code": {"type": "integer"},
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        )
        completed = run_normalizer(root_path, resources_path, out_path)
        if completed.returncode != 0:
            raise AssertionError(f"detached resource bundle failed: {completed.stderr or completed.stdout}")
        contract = json.loads(out_path.read_text(encoding="utf-8"))
        fields = contract["endpoints"]["/auth/logOff"]["POST"]["responseFields"]
        assert fields["code"]["type"] == "integer", fields

        write_json(root_path, {"openapi": "3.0.0", "paths": {"/missing": {"$ref": "/paths/missing.json"}}})
        write_json(resources_path, {})
        completed = run_normalizer(root_path, resources_path, out_path)
        assert completed.returncode != 0, "missing external ref unexpectedly succeeded"
        assert "missing external ref resource: /paths/missing.json" in completed.stderr, completed.stderr

        write_json(root_path, {"openapi": "3.0.0", "paths": {"/cycle": {"$ref": "/paths/a.json"}}})
        write_json(
            resources_path,
            {
                "/paths/a.json": {"$ref": "/paths/b.json"},
                "/paths/b.json": {"$ref": "/paths/a.json"},
            },
        )
        completed = run_normalizer(root_path, resources_path, out_path)
        assert completed.returncode != 0, "reference cycle unexpectedly succeeded"
        assert (
            "reference cycle: /paths/a.json -> /paths/b.json -> /paths/a.json" in completed.stderr
        ), completed.stderr

    print("ok normalize api contract external refs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
