"""Next.js nonce-bound execution authorization."""

from platforms import controlled_execution_authorization_v1 as _core
from platforms import nextjs_execution_binding_v1 as _binding
from platforms import nextjs_operations_v1 as _operations


def prepare_authorization(binding, *, execution_nonce):
    return _core.prepare_authorization(
        binding,
        execution_nonce=execution_nonce,
        platform_id="nextjs",
        profile_id="nextjs-standard",
        binding_module=_binding,
        operations_module=_operations,
    )


def verify_authorization(authorization, *, execution_nonce):
    return _core.verify_authorization(
        authorization,
        execution_nonce=execution_nonce,
        platform_id="nextjs",
        profile_id="nextjs-standard",
        binding_module=_binding,
        operations_module=_operations,
    )
