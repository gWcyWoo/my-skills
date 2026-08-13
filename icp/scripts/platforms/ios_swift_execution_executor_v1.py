from platforms import controlled_execution_executor_v1 as _core
from platforms import ios_execution_handler_v1 as _handler
from platforms import ios_swift_execution_authorization_v1 as _authorization


def _execute(operation_id, step, context):
    return _handler.execute("ios-swift", operation_id, step, context)


def execute_authorization(authorization, *, execution_nonce, expected_binding_digest, expected_authorization_digest):
    return _core.execute_authorization(authorization, execution_nonce=execution_nonce, expected_binding_digest=expected_binding_digest, expected_authorization_digest=expected_authorization_digest, platform_id="ios-swift", profile_id="ios-swift-standard", authorization_module=_authorization, handler=_execute)
