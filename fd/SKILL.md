---
name: fd
description: Use when converting a single Lanhu UI design URL into a frontend dev `spec.md`. Triggers on "fd", "前端开发", "蓝湖设计稿". Heavy lifting lives in `scripts/fetch.py` + `scripts/write.py`; this skill only orchestrates one URL at a time.
---

# fd

Convert one Lanhu UI design URL into a project-local `lanhu/specs/<name>/spec.md`. The skill is a thin orchestrator — `fetch.py` does the URL→JSON resolution, `write.py` renders the JSON into markdown. The main session never reads the raw Figma JSON.

The generated `spec.md` is the implementation contract for the next Flutter/UI stage. It must preserve geometry in a way that supports responsive, adaptive implementation rather than isolated absolute-position copying.

Batching across multiple URLs is the **caller's** responsibility, not this skill's. Each invocation handles exactly one URL.

## Inputs

Exactly one Lanhu UI design URL containing `image_id` in its hash query, e.g.:

    https://lanhuapp.com/web/#/item/project/board?pid=<pid>&image_id=<image_id>

Other accepted shapes: `…/stage?tid=<tid>&pid=<pid>&image_id=<image_id>` (with or without `versionId`).

If no URL is provided, ask: `请提供蓝湖设计稿 URL（含 image_id）。`

If multiple URLs are given, ask the user to invoke the skill once per URL (or to use a separate batch driver) — fd itself processes only the first URL provided and returns.

## Pipeline

The orchestrator (this skill) only runs commands and reads small one-line JSON summaries. Neither the raw Figma JSON nor the rendered spec.md ever passes through the main session — they live on disk only.

1. Resolve project root and parent dir.
   - `PROJECT_ROOT=$(git rev-parse --show-toplevel)` (fall back to `pwd` on failure).
   - `PARENT_DIR=$PROJECT_ROOT/lanhu/specs`. Create it once before the batch.

2. Fetch.
   - Run:

         python3 ~/.agents/skills/fd/scripts/fetch.py --url "<URL>" --parent-dir "$PARENT_DIR"

   - On exit 0, stdout is one line of JSON like:

         {"raw_json":"<abs path>","dir":"<abs path>","design_name":"...","design_id":"...","version_id":"...","lanhu_url":"..."}

     The script has already created the directory, sanitized the name, handled `_2`/`_3` collision suffixes, and written `raw.json` to disk.
   - Capture this small summary line; pull out `raw_json` and `dir`. Do not read `raw.json` itself.

3. Write spec.md.
   - Run:

         python3 ~/.agents/skills/fd/scripts/write.py --input "<raw_json>" --output "<dir>/spec.md"

   - Stdout is one line of JSON like `{"output":"...","text_layers":16,"shape_layers":35,"group_layers":11,"assets":2}`.
   - The written `spec.md` must include the responsive geometry requirements below in `# UI描述`.

4. Report one line: `<dir name> → lanhu/specs/<dir name>/spec.md  (text=N, shape=N, group=N, assets=N)`.

## Responsive Geometry Contract

`spec.md` must make coordinates and dimensions useful for responsive implementation. Never describe a layer's `x/y/w/h` as an isolated implementation instruction.

The UI description must include:

- Design coordinate system: artboard width/height, origin, and any viewport/device size in the source design. All layer coordinates and dimensions remain in this design coordinate system, without rounding.
- Parent context for every non-root layer: parent id/name/type, parent bbox, and child inset values `left/top/right/bottom` relative to that parent.
- Sibling context for every repeated or adjacent group: primary axis, ordering, gaps, shared alignment line, equal-width/equal-height relationships, overlap relationships, and whether the group behaves like row, column, stack, wrap, grid, or free-positioned artwork.
- Responsive intent per meaningful node: classify width and height separately as `fixed`, `proportional`, `stretch`, `content`, or `aspect-ratio`. Record the source evidence from parent/child/sibling geometry.
- Unified scaling basis: downstream implementation must calculate sizes from the design artboard and containing parent together. Do not let each widget scale independently from only its own bbox.
- Container rules: if a child fills, centers, aligns to an edge, keeps an aspect ratio, or follows sibling spacing, the spec must say so explicitly instead of leaving the implementer to infer from raw coordinates.

When the design contains a component group, the spec should describe the group first, then the children. The group-level calculation is authoritative; child coordinates are interpreted inside the group. For example, a button row must record the row width, row horizontal padding, sibling gap, shared height, and each button's proportional or fixed width before listing individual button layers.

Responsive implementation guidance for the next stage:

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

Both scripts read `LANHU_COOKIE` in this order: `--cookie` arg, `$LANHU_COOKIE`, then `~/.agents/mcp/lanhu-mcp/.env`, then the legacy Claude path `~/.claude/mcp/lanhu-mcp/.env`. The skill takes no action — just call the scripts.

## What this skill does NOT do

- No Chrome DevTools verification. The Figma JSON is the source of truth; rendering it back to compare is redundant.
- No slice download. `figma_json.assets` URLs are listed in the spec; downloading is the next stage's concern, not this skill's.
- No interpretation of `# 交互描述` / `# 数据描述`. Those stay placeholder.
- No semantic translation of layer names. Slice / layer names are recorded verbatim.
