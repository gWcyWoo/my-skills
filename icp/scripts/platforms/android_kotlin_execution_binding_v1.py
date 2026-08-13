from platforms import android_kotlin_operations_v1 as _operations
from platforms import controlled_execution_binding_v1 as _core


def prepare_binding(manifest_path, operation_id, request):
    return _core.prepare_binding(platform_id="android-kotlin", profile_id="android-kotlin-standard", operations_module=_operations, manifest_path=manifest_path, operation_id=operation_id, request=request)


def verify_binding(binding):
    return _core.verify_binding(binding, platform_id="android-kotlin", profile_id="android-kotlin-standard", operations_module=_operations)
