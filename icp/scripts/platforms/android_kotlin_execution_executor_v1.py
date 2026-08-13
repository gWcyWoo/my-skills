from platforms import android_execution_handler_v1 as _handler
from platforms import android_kotlin_execution_authorization_v1 as _authorization
from platforms import controlled_execution_executor_v1 as _core


def _execute(operation_id, step, context):
    return _handler.execute("android-kotlin", operation_id, step, context)


def execute_authorization(authorization, *, execution_nonce, expected_binding_digest, expected_authorization_digest):
    return _core.execute_authorization(authorization, execution_nonce=execution_nonce, expected_binding_digest=expected_binding_digest, expected_authorization_digest=expected_authorization_digest, platform_id="android-kotlin", profile_id="android-kotlin-standard", authorization_module=_authorization, handler=_execute)
