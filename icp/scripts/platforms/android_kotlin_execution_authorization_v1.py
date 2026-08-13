from platforms import android_kotlin_execution_binding_v1 as _binding
from platforms import android_kotlin_operations_v1 as _operations
from platforms import controlled_execution_authorization_v1 as _core


def prepare_authorization(binding, *, execution_nonce):
    return _core.prepare_authorization(binding, execution_nonce=execution_nonce, platform_id="android-kotlin", profile_id="android-kotlin-standard", binding_module=_binding, operations_module=_operations)


def verify_authorization(authorization, *, execution_nonce):
    return _core.verify_authorization(authorization, execution_nonce=execution_nonce, platform_id="android-kotlin", profile_id="android-kotlin-standard", binding_module=_binding, operations_module=_operations)
