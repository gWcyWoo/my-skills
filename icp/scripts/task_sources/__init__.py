"""ICP P1b local task-source primitives.

This package contains byte-for-byte frozen copies of proven, externally
originated primitives. The P1b runtime imports only these local copies and
never imports, executes, or symlinks anything under the read-only ``iff``
skill.

Members:

* ``csv_row_status_v1`` — frozen CSV inspect/claim/export/writeback primitive
  (SHA-256 baseline: ``d5a1f418694d002335671694c8fa419368b36919f168cfd93a33b3c2479105ae``).
"""
