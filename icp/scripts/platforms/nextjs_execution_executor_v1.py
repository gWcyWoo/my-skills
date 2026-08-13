"""Next.js controlled operation executor."""

from platforms import controlled_execution_executor_v1 as _core
from platforms import nextjs_execution_authorization_v1 as _authorization
from platforms import nextjs_execution_handler_v1 as _handler


def execute_authorization(
    authorization,
    *,
    execution_nonce,
    expected_binding_digest,
    expected_authorization_digest,
):
    return _core.execute_authorization(
        authorization,
        execution_nonce=execution_nonce,
        expected_binding_digest=expected_binding_digest,
        expected_authorization_digest=expected_authorization_digest,
        platform_id="nextjs",
        profile_id="nextjs-standard",
        authorization_module=_authorization,
        handler=_handler.execute,
    )
