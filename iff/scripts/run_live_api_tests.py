#!/usr/bin/env python3
"""Execute the current feature operation closure against a real HTTP base URL."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_path_values(value: object, path: str) -> list[object]:
    values = [value]
    for name, array_marker in re.findall(r"\.([^.[\]]+)|(\[\])", path[1:]):
        if name:
            values = [item[name] for item in values if isinstance(item, dict) and name in item]
        elif array_marker:
            values = [member for item in values if isinstance(item, list) for member in item]
    return values


def type_matches(value: object, expected: str) -> bool:
    return {
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
    }.get(expected, lambda item: True)(value)


def schema_failures(body: bytes, response: dict) -> list[str]:
    fields = response.get("fields") or {}
    if not fields:
        return []
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ["response body is not valid JSON"]
    failures = []
    for path, field in sorted(fields.items()):
        values = json_path_values(payload, str(path))
        if field.get("required") and not values:
            failures.append(f"required response field missing: {path}")
            continue
        for value in values:
            if value is None:
                if not field.get("nullable"):
                    failures.append(f"non-null response field is null: {path}")
                continue
            expected_type = str(field.get("type") or "unknown")
            if not type_matches(value, expected_type):
                failures.append(f"response field type differs: {path} expected={expected_type}")
            enum = field.get("enum")
            if enum is not None and value not in enum:
                failures.append(f"response field enum differs: {path}")
    return failures


def execute_operations(
    api_contract: dict,
    runtime: dict,
    request_config: dict,
    base_url: str,
    timeout: float,
) -> list[dict]:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base URL must be absolute HTTP(S)")
    operations = runtime.get("operations") or []
    configs = request_config.get("operations") or {}
    operation_ids = [str(operation.get("id") or "") for operation in operations]
    if set(configs) != set(operation_ids) or len(configs) != len(operation_ids):
        raise ValueError(
            f"live request operations differ: expected={operation_ids} actual={sorted(configs)}"
        )
    results = []
    for operation in operations:
        operation_id = str(operation.get("id") or "")
        endpoint = str(operation.get("endpoint") or "")
        method = str(operation.get("method") or "").upper()
        contract_operation = ((api_contract.get("endpoints") or {}).get(endpoint) or {}).get(method)
        if not isinstance(contract_operation, dict):
            raise ValueError(f"runtime operation absent from API contract: {method} {endpoint}")
        config = configs[operation_id]
        path_parameters = config.get("pathParameters") or {}
        names = re.findall(r"\{([^}]+)\}", endpoint)
        missing = [name for name in names if name not in path_parameters]
        if missing:
            raise ValueError(f"{operation_id}: missing path parameters: {missing}")
        request_path = endpoint
        for name in names:
            request_path = request_path.replace(
                "{" + name + "}", quote(str(path_parameters[name]), safe="")
            )
        query = config.get("query") or {}
        if query:
            request_path += "?" + urlencode(query, doseq=True)
        expected_status = config.get("expectedStatus")
        if not isinstance(expected_status, int):
            raise ValueError(f"{operation_id}: expectedStatus is required")
        headers = {str(key): str(value) for key, value in (config.get("headers") or {}).items()}
        body = None
        if "body" in config:
            body = json.dumps(config["body"], ensure_ascii=False).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        request = Request(
            base_url.rstrip("/") + "/" + request_path.lstrip("/"),
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                status = response.status
                response_body = response.read()
                content_type = response.headers.get_content_type()
        except HTTPError as error:
            status = error.code
            response_body = error.read()
            content_type = error.headers.get_content_type()
        except URLError as error:
            raise ValueError(f"{operation_id}: HTTP transport failed: {error.reason}") from error
        response_contract = (contract_operation.get("responses") or {}).get(str(status))
        failures = []
        if status != expected_status:
            failures.append(f"status differs: expected={expected_status} actual={status}")
        if not isinstance(response_contract, dict):
            failures.append(f"status absent from API contract: {status}")
        else:
            expected_media_type = response_contract.get("mediaType")
            if expected_media_type and content_type != expected_media_type:
                failures.append(
                    "response media type differs: "
                    f"expected={expected_media_type} actual={content_type}"
                )
            failures.extend(schema_failures(response_body, response_contract))
        results.append(
            {
                "id": operation_id,
                "method": method,
                "endpoint": endpoint,
                "requestPath": request_path,
                "status": status,
                "expectedStatus": expected_status,
                "contentType": content_type,
                "responseSha256": hashlib.sha256(response_body).hexdigest(),
                "schemaFailures": failures,
                "ok": not failures,
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-contract", required=True)
    parser.add_argument("--runtime-manifest", required=True)
    parser.add_argument("--requests", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    contract_path = Path(args.api_contract).resolve()
    runtime_path = Path(args.runtime_manifest).resolve()
    requests_path = Path(args.requests).resolve()
    try:
        results = execute_operations(
            json.loads(contract_path.read_text(encoding="utf-8")),
            json.loads(runtime_path.read_text(encoding="utf-8")),
            json.loads(requests_path.read_text(encoding="utf-8")),
            args.base_url,
            args.timeout,
        )
    except ValueError as error:
        raise SystemExit(f"ERROR: live API run failed: {error}") from error
    payload = {
        "version": 1,
        "generator": "run_live_api_tests.py",
        "ok": all(result["ok"] for result in results),
        "baseUrl": args.base_url,
        "requestConfigPath": str(requests_path),
        "requestConfigHash": sha256(requests_path),
        "apiContractHash": sha256(contract_path),
        "runtimeManifestHash": sha256(runtime_path),
        "checkedOperations": [result["id"] for result in results],
        "results": results,
    }
    Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not payload["ok"]:
        raise SystemExit("ERROR: live API responses failed status/schema verification")
    print(f"ok live API operations={len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
