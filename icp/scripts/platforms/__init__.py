"""ICP P2c platform-adapter descriptors.

This package contains non-executable platform-adapter descriptors that
structure the existing vendored iFF platform-specific script families
under the nine settled platform operation ports. Each descriptor binds
every mapped primitive to the immutable capsule manifest SHA-256 and
remains fail-closed / inactive until later executable builders and parity
gates are complete.

Members:

* ``flutter_standard_v1`` — Flutter ``flutter-standard`` platform-adapter
  descriptor (``icp.platform-adapter-descriptor.v1``). It is a descriptor
  only: ``executable`` is ``false``, ``activation_state`` is ``inactive``,
  and no operation may carry an executable/command/argv/shell field. The
  descriptor drives no platform tooling, code generation, packaging,
  capture, parity gate, or claim. The public Python API exposes only
  ``describe()`` and ``verify_descriptor()``; the CLI exposes only
  ``describe`` and ``verify`` and accepts no path, registry, command,
  executable, script, interpreter, environment, argv, or activation
  override.
"""
