---
name: fd
description: Use when converting one Lanhu design URL containing image_id into project-local spec.md and assets for fc. Triggers on "fd", "前端开发", "蓝湖设计稿".
---

# fd

Convert exactly one Lanhu design URL into `lanhu/specs/<name>/spec.md`. Use `scripts/fetch.py` and `scripts/write.py`; read only their one-line JSON summaries in the main session. Do not read `raw.json`.

## Inputs

Required: one Lanhu URL containing `image_id` in its hash query, e.g.:

    https://lanhuapp.com/web/#/item/project/board?pid=<pid>&image_id=<image_id>

Also accepted: `.../stage?tid=<tid>&pid=<pid>&image_id=<image_id>` with or without `versionId`.

If no URL is provided, ask: `请提供蓝湖设计稿 URL（含 image_id）。`

If multiple URLs are provided, stop and ask for one URL or a separate batch driver.

## Pipeline

1. Resolve project root and parent dir.
   - `PROJECT_ROOT=$(git rev-parse --show-toplevel)` (fall back to `pwd` on failure).
   - `PARENT_DIR=$PROJECT_ROOT/lanhu/specs`. Create it before running scripts.

2. Fetch.
   - Run:

         python3 ~/.claude/skills/fd/scripts/fetch.py --url "<URL>" --parent-dir "$PARENT_DIR"

   - On exit 0, stdout is one line of JSON like:

         {"raw_json":"<abs path>","dir":"<abs path>","design_name":"...","design_id":"...","version_id":"...","lanhu_url":"..."}

     The script has already created the directory, sanitized the name, handled `_2`/`_3` collision suffixes, and written `raw.json` to disk.
   - Capture `raw_json` and `dir`. Do not read `raw.json`.
   - `fetch.py` downloads exportable slices to `<dir>/assets/` when present.

3. Write spec.md.
   - Run:

         python3 ~/.claude/skills/fd/scripts/write.py --input "<raw_json>" --output "<dir>/spec.md"

   - Stdout is one line of JSON like `{"output":"...","text_layers":16,"shape_layers":35,"group_layers":11,"assets":2}`.
   - `spec.md` must include the geometry contract below in `# UI描述`.

4. Report one line: `<dir name> → lanhu/specs/<dir name>/spec.md  (text=N, shape=N, group=N, assets=N)`.

## Responsive Geometry Contract

Never describe a layer's `x/y/w/h` as an isolated implementation instruction.

`# UI描述` must include:

- Design coordinate system: artboard width/height, origin, and any viewport/device size in the source design. All layer coordinates and dimensions remain in this design coordinate system, without rounding.
- Parent context for every non-root layer: parent id/name/type, parent bbox, and child inset values `left/top/right/bottom` relative to that parent.
- Sibling context for every repeated or adjacent group: primary axis, ordering, gaps, shared alignment line, equal-width/equal-height relationships, overlap relationships, and whether the group behaves like row, column, stack, wrap, grid, or free-positioned artwork.
- Responsive intent per meaningful node: classify width and height separately as `fixed`, `proportional`, `stretch`, `content`, or `aspect-ratio`. Record the source evidence from parent/child/sibling geometry.
- Unified scaling basis: downstream implementation must calculate sizes from the design artboard and containing parent together. Do not let each widget scale independently from only its own bbox.
- Container rules: if a child fills, centers, aligns to an edge, keeps an aspect ratio, or follows sibling spacing, the spec must state that relationship explicitly.

When the design contains a component group, describe the group before its children. The group-level calculation is authoritative; child coordinates are interpreted inside the group.

Implementation guidance for fc:

- Use the artboard size as the base design size.
- Compute layout from parent constraints plus sibling relationships before assigning child dimensions.
- Prefer proportional/stretched constraints for app UI regions and reserve raw absolute positioning for decorative or intentionally fixed artwork.
- Preserve aspect ratio for image slices and icon artwork unless the layer relationship explicitly shows stretch.
- Treat mismatches between individual bbox values and parent/sibling geometry as ambiguity to resolve from `raw.json`, not as permission to hard-code independent absolute sizes.

## Errors

If `fetch.py` or `write.py` exits non-zero:

- Read stderr from the failing script (1–3 lines, contains `ERROR: ...`).
- `fetch.py` creates no directory until all data has been fetched, so a fetch failure leaves nothing to clean up — just report the URL + cause.
- If `write.py` fails, the directory containing `raw.json` exists. Rename it from `<sanitized_name>` to `<sanitized_name>_err` and write `error.txt` inside with the stderr message. Do not delete `raw.json`.
- Report the failure to the user and stop.

## Cookie

Both scripts read `LANHU_COOKIE` in this order: `--cookie`, `$LANHU_COOKIE`, `~/.claude/mcp/lanhu-mcp/.env`, `~/.agents/mcp/lanhu-mcp/.env`. Do not read cookie files in the main session.

## Boundaries

- No Chrome DevTools verification. The Lanhu/Figma JSON is the source of truth.
- No manual `raw.json` inspection.
- No manual slice fetching; `fetch.py` handles exportable slices.
- No interpretation of `# 交互描述` or `# 数据描述`; keep placeholders.
- No semantic translation of layer names. Record slice and layer names verbatim.
