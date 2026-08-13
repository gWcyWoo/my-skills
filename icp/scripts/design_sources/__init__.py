"""ICP P2b DesignSource wrappers.

This package contains self-contained DesignSource adapters that drive the
immutable, integrity-gated iFF v1 capsule under ``icp/vendor/iff_v1/scripts``
without importing sibling ``iff/`` at runtime.

Members:

* ``lanhu_figma_v1`` — Lanhu/Figma DesignSource wrapper exposing the four
  settled operations ``resolve``, ``probe``, ``fetch_normalize`` and
  ``verify_bundle``. No public override is exposed for the ICP root, capsule
  root, script path, command, interpreter, runner, environment, or registry.
"""
