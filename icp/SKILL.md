---
name: icp
description: Build a source-bound, staged design-to-code contract. Use when a user invokes ICP, asks to extract one or many Lanhu designs into trustworthy structured data, or wants the phased extract, component-design, implementation, fidelity, and final-interaction workflow. The current implementation covers only the extract stage.
---

# ICP

Turn rendered designs and their machine-readable sources into reviewable contracts. Keep model interpretation separate from deterministic facts and block every transition unless its exact gate passes.

## Route the request

The only implemented stage is `extract`. Read [extract/STAGE.md](extract/STAGE.md) completely before running it.

Do not create placeholder directories or pretend to run later stages. Component design, implementation, fidelity acceptance, and interaction/final inspection remain pending until their own contracts exist.

## Project-owned artifacts

Write process artifacts under the target project, one directory per design:

```text
<project>/.icp/extract/<design-name>/
```

The batch manifest, index, and result live directly in `.icp/extract/`. Preserve this directory on failure because its hashes, revisions, and repair packets are evidence.

## Self-contained boundary

ICP owns its Lanhu acquisition path: URL parsing, configured-cookie resolution, HTTP and gzip handling, metadata and design JSON retrieval, complete cover validation, exported-slice discovery, downloads, and hashes. Do not call, import, or locate another skill at runtime.

The model may interpret semantics, roles, hierarchy, relationships, and source-node classifications. It may not invent source IDs, dimensions, colors, spacing values, or other exact facts. Scripts own source normalization, hashes, exact partitions, source-node-to-local-asset references, reference-pixel-to-logical-coordinate mapping, repair packets, state transitions, and completion verification.

An individual design is complete only when this exits zero:

```bash
python3 <icp-skill>/extract/scripts/extract.py verify \
  --project-root <project> \
  --design-name <design-name>
```

A multi-design run is deliverable only when `verify-run` exits zero. Stop after reporting the verified extract result; do not begin component design implicitly.
