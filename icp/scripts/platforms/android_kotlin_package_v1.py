import hashlib
from pathlib import Path

from platforms import inactive_platform_core_v1 as _core

_TRANSITIVE_SHA256 = {
    "platform_package_contract_v1.py": "92b574a8dc056628f45946ec957386c6e1807be355fcd66b71f9a9b8333a51e3",
    "inactive_platform_core_v1.py": "3aff42141a32bf1ba6fdb3f11de877484c09acf39d1b7ef1e01c926e6e6eb4bd",
    "controlled_platform_operations_v1.py": "c513c263219736ef1f536eb7873edd411b0cc3793341ad6cf4322a91c390ce3c",
    "controlled_execution_binding_v1.py": "d270af4ef02db0f6611e3becd72506a4fdc131d9565abf3d61ba2e02d2245775",
    "controlled_execution_authorization_v1.py": "0492265d93b6fb5729f64f644f9bc5863d2dff94593b82c868e1c42654d0019b",
    "controlled_execution_executor_v1.py": "cf9d431ec460d7a6e1cadf49236ce2ab6b1221bcd35bf433b2bf74b23601e4ab",
    "android_execution_handler_v1.py": "f9b4633f046a9b7cc353780f4371cb0d4e33960814c27dfd05654b212f09921f",
}


def _verify_transitive() -> None:
    root = Path(__file__).resolve().parent
    for basename, expected in _TRANSITIVE_SHA256.items():
        path = root / basename
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError("platform package transitive integrity failed")


def describe_package():
    return _core.describe_package(
        platform_id="android-kotlin",
        profile_id="android-kotlin-standard",
        stem="android_kotlin",
        actual_source_type="emulator_screenshot",
        toolchain_shape="shape.android_kotlin_toolchain",
        activation_state="active",
        executable=True,
        binding_basename="android_kotlin_execution_binding_v1.py",
        authorization_basename="android_kotlin_execution_authorization_v1.py",
        executor_basename="android_kotlin_execution_executor_v1.py",
    )


def verify_package():
    _verify_transitive()
    return _core.verify_package(describe_package())
