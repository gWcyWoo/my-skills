#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib
import json
import tempfile
from pathlib import Path

import freeze_selection_manifest
import platform_package_resolver_v1 as resolver
from platforms import inactive_execution_executor_v1
from platforms import platform_package_contract_v1 as contract


PLATFORMS = (
    ("android-java", "android-java-standard", "android_java"),
    ("android-kotlin", "android-kotlin-standard", "android_kotlin"),
    ("ios-objc", "ios-objc-standard", "ios_objc"),
    ("ios-swift", "ios-swift-standard", "ios_swift"),
    ("nextjs", "nextjs-standard", "nextjs"),
)


def _references(name: str) -> dict:
    path = Path(__file__).resolve().parents[1] / "references" / name
    return json.loads(path.read_text(encoding="utf-8"))


def _project(root: Path, platform_id: str) -> None:
    if platform_id == "nextjs":
        (root / "package.json").write_text(
            json.dumps(
                {
                    "name": "icp-next-fixture",
                    "scripts": {"build": "next build", "test": "node --test"},
                    "dependencies": {"next": "15.0.0", "react": "19.0.0"},
                }
            ),
            encoding="utf-8",
        )
        (root / "next.config.js").write_text("export default {};\n", encoding="utf-8")
    elif platform_id.startswith("ios-"):
        (root / "Fixture.xcodeproj").mkdir()
        extension = ".swift" if platform_id == "ios-swift" else ".m"
        (root / f"App{extension}").write_text("// fixture\n", encoding="utf-8")
    else:
        (root / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
        (root / "settings.gradle").write_text("rootProject.name='Fixture'\n", encoding="utf-8")
        source = root / "app" / "src" / "main"
        source.mkdir(parents=True)
        extension = ".java" if platform_id == "android-java" else ".kt"
        (source / f"Main{extension}").write_text("// fixture\n", encoding="utf-8")


def test_all_configured_platform_packages_resolve_live_and_are_active() -> None:
    registry = _references("registries.json")
    index = _references("platform_packages_v1.json")
    resolver.verify_package_index(index)
    for platform_id, profile_id, stem in PLATFORMS:
        package = importlib.import_module(f"platforms.{stem}_package_v1")
        descriptor = package.describe_package()
        contract.validate_descriptor(descriptor)
        assert package.verify_package()["ok"] is True
        row = next(
            item
            for item in index["packages"]
            if item["platform_id"] == platform_id and item["profile_id"] == profile_id
        )
        module_path = Path(package.__file__)
        assert row["package_module_sha256"] == hashlib.sha256(module_path.read_bytes()).hexdigest()
        assert row["package_descriptor_digest"] == contract.compute_descriptor_digest(descriptor)
        resolution = resolver.resolve_package(
            platform_id=platform_id,
            profile_id=profile_id,
            registries=registry,
            package_index=index,
            package_descriptor=descriptor,
            package_module_bytes=module_path.read_bytes(),
        )
        assert resolution["activation_state"] == "active"
        assert resolution["executable"] is True


def test_each_platform_has_static_plan_and_generic_run_root() -> None:
    for platform_id, profile_id, stem in PLATFORMS:
        with tempfile.TemporaryDirectory(prefix=f"icp-p4-{stem}-") as directory:
            project = Path(directory).resolve() / "project"
            project.mkdir()
            _project(project, platform_id)
            state_root, run_root = freeze_selection_manifest.derive_roots(
                platform_id, project, "p4-batch"
            )
            run_root.mkdir(parents=True)
            assert state_root == project / ".icp"
            input_path = run_root / "inputs" / "contract.json"
            input_path.parent.mkdir(parents=True)
            input_path.write_text("{}\n", encoding="utf-8")
            output_parent = project / "generated"
            output_parent.mkdir()
            operations = importlib.import_module(f"platforms.{stem}_operations_v1")
            operation_id = operations.list_operation_ids()[0]
            plan = operations.build(
                operation_id,
                {
                    "project_root": str(project),
                    "run_root": str(run_root),
                    "feature_id": "login",
                    "inputs": {
                        "contract": {"root": "run", "path": "inputs/contract.json"}
                    },
                    "outputs": {
                        "source": {"root": "project", "path": "generated/login.txt"}
                    },
                },
            )
            assert operations.verify_plan(plan)["plan_digest"]


def test_common_inactive_executor_fails_before_effect() -> None:
    try:
        inactive_execution_executor_v1.execute_authorization({})
    except inactive_execution_executor_v1.InactiveExecutionError as exc:
        assert "inactive" in str(exc)
    else:
        raise AssertionError("inactive platform executor must fail closed")


def main() -> int:
    tests = sorted(
        (name, value)
        for name, value in globals().items()
        if name.startswith("test_") and callable(value)
    )
    failures = 0
    for name, test in tests:
        try:
            test()
        except Exception as exc:  # pragma: no cover
            failures += 1
            print(f"not ok {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok {name}")
    if failures:
        print(f"failed {failures}/{len(tests)} selftest cases")
        return 1
    print(f"ok {len(tests)} selftest cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
