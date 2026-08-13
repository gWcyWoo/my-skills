#!/usr/bin/env python3
"""RED/GREEN contract for audited ICP platform activation."""

from __future__ import annotations

import copy
import json
import sys
import traceback
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from platforms import platform_package_contract_v1 as contract  # noqa: E402
from platforms import flutter_package_v1  # noqa: E402
from platforms import nextjs_package_v1  # noqa: E402
from platforms import vue_package_v1  # noqa: E402
import icp_entry_v1  # noqa: E402
import preflight_selection  # noqa: E402
import platform_package_resolver_v1 as resolver  # noqa: E402


def _descriptor() -> dict:
    descriptor = copy.deepcopy(vue_package_v1.describe_package())
    descriptor["activation_state"] = "active"
    descriptor["executable"] = True
    return descriptor


def test_active_executable_descriptor_is_valid() -> None:
    contract.validate_descriptor(_descriptor())


def test_active_non_executable_descriptor_is_rejected() -> None:
    descriptor = _descriptor()
    descriptor["executable"] = False
    try:
        contract.validate_descriptor(descriptor)
    except contract.PlatformPackageDescriptorError:
        return
    raise AssertionError("active/non-executable descriptor was accepted")


def test_inactive_executable_descriptor_is_rejected() -> None:
    descriptor = _descriptor()
    descriptor["activation_state"] = "inactive"
    try:
        contract.validate_descriptor(descriptor)
    except contract.PlatformPackageDescriptorError:
        return
    raise AssertionError("inactive/executable descriptor was accepted")


def test_live_flutter_package_resolves_active_and_executable() -> None:
    icp_root = SCRIPT_ROOT.parent
    registries = json.loads((icp_root / "references" / "registries.json").read_text())
    package_index = json.loads(
        (icp_root / "references" / "platform_packages_v1.json").read_text()
    )
    resolution = resolver.resolve_package(
        platform_id="flutter",
        profile_id="flutter-standard",
        registries=registries,
        package_index=package_index,
        package_descriptor=flutter_package_v1.describe_package(),
        package_module_bytes=Path(flutter_package_v1.__file__).read_bytes(),
    )
    assert resolution["activation_state"] == "active"
    assert resolution["executable"] is True


def test_live_seven_package_resolutions_pass_package_aware_gate() -> None:
    registries = json.loads(icp_entry_v1.REGISTRY_PATH.read_text(encoding="utf-8"))
    for platform_id, platform in registries["platforms"].items():
        profile_id = platform["profiles"][0]
        config = {
            "task_source": "csv",
            "task_ref": "/dev/null",
            "design_source": "lanhu-figma",
            "platform": platform_id,
            "project_root": "/tmp",
            "profile": profile_id,
        }
        _, _, resolution = icp_entry_v1._resolve_package(config, registries)
        result = preflight_selection.support_gate_package_aware(config, registries, resolution)
        assert result.ok, (platform_id, result.code, result.message)


def test_controlled_package_rejects_transitive_digest_drift() -> None:
    basename = "controlled_platform_operations_v1.py"
    expected = nextjs_package_v1._TRANSITIVE_SHA256[basename]
    nextjs_package_v1._TRANSITIVE_SHA256[basename] = "0" * 64
    try:
        try:
            nextjs_package_v1.verify_package()
        except RuntimeError as exc:
            assert str(exc) == "platform package transitive integrity failed"
        else:
            raise AssertionError("transitive dependency drift was accepted")
    finally:
        nextjs_package_v1._TRANSITIVE_SHA256[basename] = expected


def main() -> int:
    tests = sorted(name for name in globals() if name.startswith("test_"))
    failures = 0
    for name in tests:
        try:
            globals()[name]()
            print(f"ok {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"not ok {name}: {type(exc).__name__}: {exc}")
            traceback.print_exc()
    if failures:
        print(f"failed {failures}/{len(tests)} selftest cases")
        return 1
    print(f"ok {len(tests)} selftest cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
