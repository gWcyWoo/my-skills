"""ICP SharedCore — platform-neutral contracts.

P2.5a1 adds exactly one contract here: the expected/slots projection
(``expected_slots_projection_v1``). SharedCore owns no platform behavior, no
execution authority, and no I/O; it only validates a strict projection and
deterministically reconstructs the frozen legacy expected/slots sidecar
documents.

This package must remain standard-library-only and must never import a
platform module or the iFF v1 compatibility capsule.
"""
