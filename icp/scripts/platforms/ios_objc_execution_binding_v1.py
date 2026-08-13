from platforms import controlled_execution_binding_v1 as _core
from platforms import ios_objc_operations_v1 as _operations


def prepare_binding(manifest_path, operation_id, request):
    return _core.prepare_binding(platform_id="ios-objc", profile_id="ios-objc-standard", operations_module=_operations, manifest_path=manifest_path, operation_id=operation_id, request=request)


def verify_binding(binding):
    return _core.verify_binding(binding, platform_id="ios-objc", profile_id="ios-objc-standard", operations_module=_operations)
