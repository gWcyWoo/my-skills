---
name: fc
description: Use when implementing Flutter UI from a Lanhu-derived spec.md. Triggers on "fc", "flutter 实现", "蓝湖→Flutter". Caller passes the absolute spec.md path; the output and common widget directories are detected from the Flutter project structure.
---

<role>
Flutter UI implementer in the MAIN session. Converts one Lanhu `spec.md` into responsive Flutter widget files compliant with `flutter-widget.md`. Never invents layout the spec does not support. Never claims `flutter analyze` passed without running it. Never substitutes placeholders for missing image slices. Never writes a layout or component without a rationale comment in idiomatic technical English. Never re-implements a widget the project already has — searches the codebase via the `my-explore-0` skill first and reuses what fits. Never implements isolated absolute coordinates or dimensions from a layer bbox without first calculating them against the design artboard, parent container, and sibling relationships.
</role>

<context>
**`~/.code/shared-rules/frontend/flutter-widget.md`** — 337 lines. Never read in full.
1. `rg -n "^#" ~/.code/shared-rules/frontend/flutter-widget.md` to enumerate sections.
2. Read only the matching section with Codex's available targeted file-read tool or `rg -n -C`.

Section map:
- `#1` 布局 — Column / Row / Stack / Expanded / Flexible / Wrap / Container / Padding / Center / Align / Positioned / SizedBox / ConstrainedBox / AspectRatio / LayoutBuilder.
- `#2` 滚动与集合 — SingleChildScrollView / ListView(.builder/.separated) / GridView / PageView / CustomScrollView / Sliver*.
- `#3` 页面骨架 — Scaffold / SafeArea / AppBar / Drawer / BottomNavigationBar / NavigationBar / TabBar / FAB / BottomSheet / SnackBar.
- `#4` 展示 — Text / RichText / SelectableText / Image / Icon / Card / ListTile / Divider / Chip.
- `#5` 输入与表单.
- `#6` 交互与按钮.
- `#7` 异步、状态与 Builder.
- `#8` 动画.
- `#10` 决策树 — 10.1 布局 / 10.2 表单 / 10.3 异步 / 10.4 交互 / 10.5 动画.
- `#11` 反模式 — must not violate.

**`raw.json`** — sibling of spec.md. Consulted ONLY to resolve a step-4 ambiguity. Schema: `{design_name, design_id, version_id, lanhu_url, figma_json: {meta, assets, artboard: {layers: [...]}}}`. Always queried via `~/.agents/skills/fc/scripts/inspect_layers.py` — never bulk-read, never inline `jq`/`grep`/Python.

**Layer-query helper — `~/.agents/skills/fc/scripts/inspect_layers.py`**:
- Invocation: `python3 ~/.agents/skills/fc/scripts/inspect_layers.py --raw-json <path> [--ids ID,ID,…] [--type textLayer|shapeLayer|groupLayer|artboard] [--name-contains SUBSTR]`.
- Output (one line of compact JSON to stdout): list of normalized records `{id, type, name, path, parent_id, frame:{x,y,w,h}, visible, text_content, font:{size,weight,family}, text_color, fill_color, asset}`. Fields irrelevant to the layer type are omitted.
- Handles both raw.json schemas (`figma_json.artboard` and stripped `artboard`).
- Newlines inside `text_content` are preserved verbatim (matches what the Dart literal must decode to after escape-decoding).
- Exit codes: `0` ok / `2` input error.

**Visual-hierarchy rules** (applied to spec.md's flat layer list):
- Same x-range, vertical stacking, uniform vertical gap → siblings in `Column`.
- Same y-range, horizontal arrangement, uniform horizontal gap → siblings in `Row`.
- Identical fill / border / radius repeating across N layers with identical inner layout → N siblings reusing one extracted widget; outer container chosen per `#10.1`.
- Bounding-box overlap → child of `Stack` with `Positioned`.
- A single background block enclosing several layers → those layers share one parent `Container` / `Card` with matching decoration.
- Pattern repeating ≥3 times → one widget file + `.map` over data. No paste-copy.

**Responsive geometry rules** (mandatory implementation contract from `fd`):
- Treat the design artboard width/height as the base coordinate system. Convert design px to runtime values through the available parent constraints, not through independent per-widget scaling.
- Before assigning any width/height/offset, calculate the node against its parent bbox/insets and sibling group: parent `left/top/right/bottom`, sibling gap, shared axis, shared alignment, equal-size relationships, overlap, and aspect ratio.
- Classify every meaningful node's width and height separately as `fixed`, `proportional`, `stretch`, `content`, or `aspect-ratio` before writing code. The classification must come from parent-child and sibling evidence in `spec.md`; use `inspect_layers.py` only when the spec is ambiguous.
- Prefer Flutter constraint widgets (`LayoutBuilder`, `Expanded`, `Flexible`, `Spacer`, `AspectRatio`, `FractionallySizedBox`, `Align`, `Padding`, `ConstrainedBox`) when they express the parent/sibling relationship. Use raw `Positioned(left/top/width/height)` only for genuine overlap, decorative artwork, or explicitly fixed artboard-relative elements.
- Group-level calculation is authoritative. For a component group, implement the container/row/column/grid sizing first, then calculate children inside that group. Do not let children scale independently from their own bboxes.
- Preserve image/icon aspect ratio unless the parent/sibling geometry explicitly proves stretch. Do not distort slices to satisfy a raw bbox.
- If individual bboxes conflict with parent/sibling geometry, STOP and resolve the ambiguity through `inspect_layers.py`; do not choose hard-coded absolute values by default.

**Project-layout detection** — `<root>` = nearest ancestor of spec.md (or cwd) that contains `pubspec.yaml`. `<design_name>` = basename of spec.md's parent directory or the design name recorded in spec.md. `<feature_slug>` = semantic English ASCII `lower_snake_case` name derived from `<design_name>`.

**Flutter code naming policy**:
- `lanhu/specs/<design_name>/` may keep the original design name, including Chinese. Generated Flutter code paths under `<root>/lib/` must never use Chinese or any non-ASCII path segment.
- Derive `<feature_slug>` as concise semantic English, `lower_snake_case`, `[a-z0-9_]+` only. Examples: `信息列表页-有信息状态` → `information_list_with_status`; `信息列表页-无信息状态` → `information_list_empty_state`.
- Do NOT use raw Chinese, spaces, hyphens, punctuation, pinyin, or mixed-language names for directories, Dart filenames, widget filenames, class names, imports, or part names.
- Dart files use `lower_snake_case.dart`; Dart classes use ASCII `UpperCamelCase`; private members use ASCII `_lowerCamelCase`.
- If semantic translation is ambiguous, derive `screen_<image_id8>` from the Lanhu `image_id` in spec.md instead of using the Chinese name. Surface the fallback in output. If no `image_id` is available, STOP and ask for an English feature slug.

Page-layer convention (FIRST existing match under `<root>/lib/`):
- `lib/pages/` → `<root>/lib/pages/<feature_slug>/`.
- `lib/features/` → `<root>/lib/features/<feature_slug>/presentation/`.
- `lib/screens/` → `<root>/lib/screens/<feature_slug>/`.
- `lib/views/` → `<root>/lib/views/<feature_slug>/`.

Common-widget convention (FIRST existing match under `<root>/lib/`):
- `lib/widgets/` → `<root>/lib/widgets/`.
- `lib/components/` → `<root>/lib/components/`.
- `lib/shared/widgets/` → `<root>/lib/shared/widgets/`.
- `lib/common/widgets/` → `<root>/lib/common/widgets/`.
- None exist → default `<root>/lib/widgets/` (created on first reusable write; surfaced to user in step 2g).

**Reuse policy** — for every non-leaf node in the hierarchy tree, classify the implementation source:
- **Reused** — an existing project widget under `<root>/lib/` (located via `my-explore-0` in step 7) whose signature and visual semantics match the node. Import and call. Do NOT re-implement.
- **New common** — a generic primitive (button / input row / list item / card head / status badge / divider with brand) NOT yet in the project, expected to recur on ≥2 pages. Write to `{{COMMON_DIR}}`.
- **New feature** — coupled to this page's business semantics (page-specific footer, page-specific form-row with bespoke validation). Write to `{{OUTPUT_DIR}}`.
- **Default when uncertain** — feature dir. Promotion to common dir requires the user OK in a later run; never auto-promote.

**Comment policy** — every layout widget (Column / Row / Stack / Wrap / Flex / Expanded / Flexible / Padding / Center / Align / Positioned / Container-as-layout) and every non-layout component (Text / Image / Icon / Button / Field / Card / ListTile / etc.) carries a one- or two-line leading `// …` comment in idiomatic technical English stating WHY this widget was chosen and WHY it is optimal versus the next-best alternative, citing the `flutter-widget.md` section. For reused project widgets, the comment additionally cites the source `file:line` and explains why reuse beats a fresh local widget. No Chinese characters. No filler ("// this is a column"). The comment must add information the widget name does not.

**Lanhu MCP** — `mcp__lanhu__lanhu_get_design_slices`. Used ONLY to fetch a slice referenced by spec.md but absent from disk. Design URL lives in spec.md's header (`图：…` or `lanhu_url:`). Save to `<spec_dir>/assets/`.

**Static visual-correctness check — `~/.agents/skills/fc/scripts/check_static.py`**:
- Invocation: `python3 ~/.agents/skills/fc/scripts/check_static.py --raw-json <spec_dir>/raw.json --code-dir {{OUTPUT_DIR}}`.
- Input: `raw.json` (design ground truth) + every `.dart` file under `{{OUTPUT_DIR}}` (excluding `test/`).
- Output (one line of JSON to stdout): `{"expected","matched","mismatches":[{layer_id,kind,expected,actual,file,line}],"unmatched_design":[...],"unmatched_code":[...]}`. `kind` ∈ `color | text | font_size | font_weight | asset`.
- Exit codes: `0` = clean (matched == expected, no mismatches, no unmatched_design); `1` = check failed; `2` = input error.
- Coverage (Tier 1): declared literals only — `Color(0x…)`, `Color.fromARGB(…)`, `Text("…")`, `AssetImage("…")`, `fontSize: <num>`, `fontWeight: FontWeight.w<n>|bold|normal`. Bbox / runtime layout out of scope.
- Theme references (`theme.colorScheme.primary`, `Colors.red[500]`) are intentionally NOT recognized — the comment policy + `spec values verbatim` rule means every visible value must be a literal.
- The check covers code in `{{OUTPUT_DIR}}` only. Reused widgets under `<root>/lib/` are NOT re-scanned — the call site's `child:` / decoration overrides are what gets verified for the current page.
</context>

<instructions>
1. **Resolve `{{SPEC_PATH}}`.** Absolute path required. If only a directory is passed, append `/spec.md`. If the file is missing → STOP: `spec.md not found at <path>`.
2. **Detect `{{OUTPUT_DIR}}` and `{{COMMON_DIR}}`.**
   2a. Walk up from spec.md's directory and from cwd; the first directory containing `pubspec.yaml` is `<root>`. If none → STOP: `pubspec.yaml not found; cannot resolve Flutter project root`.
   2b. `<design_name>` = basename of spec.md's parent directory unless spec.md records a more precise design name. Derive `<feature_slug>` per the Flutter code naming policy.
   2c. Validate `<feature_slug>` against `^[a-z][a-z0-9_]*$`. If invalid, fix the slug before continuing; never create a `lib/` directory with raw Chinese or any non-ASCII segment.
   2d. Pick the first existing page-layer convention per the `<context>` table; build `{{OUTPUT_DIR}}` with `<feature_slug>` accordingly.
   2e. None of the four page conventions exist → STOP and ask: `lib/ has no pages|features|screens|views subdir; please supply the Flutter output directory (absolute ASCII path).`
   2f. If the detected or user-supplied `{{OUTPUT_DIR}}` contains any non-ASCII path segment under `<root>/lib/` → STOP and ask for an English ASCII feature slug or output path.
   2g. The detected `{{OUTPUT_DIR}}` already exists and contains `.dart` files → STOP and ask: `<path> is already populated; overwrite, append, or use a different path?`
   2h. Pick the first existing common-widget convention per the `<context>` table; that is `{{COMMON_DIR}}`.
   2i. None exist → set `{{COMMON_DIR}} = <root>/lib/widgets/` and surface it in tick output (`Common dir: defaulted <path> (will be created on first reusable widget)`). Do NOT mkdir yet — only when step 10 actually writes a reusable widget.
3. **Read spec.md fully.** Capture design URL, design artboard width/height, layer counts, every layer's bbox / parent context / sibling context / responsive intent / color / font, and every image-asset path. Do not touch `raw.json` yet.
4. **Derive the hierarchy tree and responsive geometry plan.** Apply `<context>` rules to produce `Page → Section → Item → Atom`, naming the candidate widget per node. For every non-root node, record `(parent, sibling_group, width_mode, height_mode, runtime_formula_or_constraint, aspect_ratio_if_any)`. Record every layer pair whose relationship or responsive mode cannot be decided from spec.md alone — these are the step-5 ambiguities. Think thoroughly before writing any code.
5. **Resolve ambiguities via `inspect_layers.py`.** For each step-4 ambiguity, run `python3 ~/.agents/skills/fc/scripts/inspect_layers.py --raw-json <spec_dir>/raw.json` with `--ids` / `--type` / `--name-contains` to fetch the missing field (parent_id, frame, fill, text content + font + color). One query per ambiguity. NEVER write inline Python / `jq` / `grep` against raw.json — the helper handles the wrapper schema, the color normalization, and the text-content newline preservation; ad-hoc queries silently miss the `figma_json.artboard` nesting and produce false zeros.
6. **Pick widgets per `flutter-widget.md` and the responsive geometry plan.**
   6a. Run `rg -n "^#" ~/.code/shared-rules/frontend/flutter-widget.md` once; cache section line numbers.
   6b. Read only the section relevant to each non-leaf decision using a targeted file-read tool or `rg -n -C`.
   6c. Record `(node, sdk_widget, section#, width_mode, height_mode, why-optimal)` for each non-leaf node. This is the step-7 reuse-search input.
   6d. If a node can be expressed by parent constraints and sibling relationships, prefer responsive Flutter constraints over raw design-px offsets. Raw absolute positioning requires an explicit `Stack`/overlap/decorative rationale.
7. **Search the project for reusable widgets via `my-explore-0`.**
   7a. Build ONE batched query naming every candidate role from step 6 (e.g. `primary button`, `phone input row`, `password input row with show toggle`, `centered footer link`). For each, supply the SDK widget chosen in step 6, the visual-semantics summary from spec.md, and the required responsive width/height modes.
   7b. Use the `my-explore-0` skill in the MAIN session: announce `Using my-explore-0 to search reusable Flutter widgets.` and follow `~/.agents/skills/my-explore-0/SKILL.md`. Do NOT create a child agent for this search; the `-0` suffix denotes MAIN-session skill execution. Pass the batched query; ask for `file:line` of every matching `class … extends StatelessWidget|StatefulWidget` under `<root>/lib/`, with constructor signature.
   7c. For each step-6 node, classify the source per the `<context>` Reuse policy: **reused** | **new-common** | **new-feature**. Reuse only if (signature compatible) AND (visual semantics match the spec). Cosmetic mismatch on a reused widget → wrap with overrides at the call site (color, padding); do NOT modify the reused widget itself (changes leak to other pages — see P0).
   7d. Record `(node, source, target_file)` for the `Reuse` slot. The target_file for `reused` is the existing path; for `new-common` it is `{{COMMON_DIR}}/<widget_slug>.dart`; for `new-feature` it is `{{OUTPUT_DIR}}/<widget_slug>.dart`. Every `<widget_slug>` must be ASCII `lower_snake_case`.
8. **Pause for user review of the implementation plan.** Before creating any directory or writing any Dart file, emit `<plan_review_format>` and ask: `我已根据 spec.md 抽象出视觉层次、组件拆分和 Flutter 布局方案。请审核：是否有布局或组件拆分建议？确认后我再开始实现代码。`
   8a. The plan must include visual hierarchy, responsive geometry modes, Flutter SDK/layout choices with `flutter-widget.md` section citations, reuse classification, proposed ASCII paths/files, and open ambiguities.
   8b. If the user suggests changes, revise the plan and ask for confirmation again. Do not write code until the user explicitly confirms the plan.
   8c. If the user confirms, record `Plan review: accepted` or `Plan review: accepted-after-changes` and continue.
9. **Resolve missing slices.**
   9a. List every image-asset path in spec.md whose file does not exist on disk.
   9b. For each, call `mcp__lanhu__lanhu_get_design_slices` with the design URL from spec.md; save into `<spec_dir>/assets/`.
   9c. MCP unavailable or returns nothing → STOP with `Status: blocked` and the missing-asset list. No placeholder substitution.
10. **Write responsive widgets with rationale comments from the confirmed plan.** Create new files with Codex's file-editing tools (`apply_patch` for manual edits). The page entry-point goes under `{{OUTPUT_DIR}}`; new reusable primitives go under `{{COMMON_DIR}}` (mkdir on first such write); reused widgets are imported, not re-implemented. `const` where children are compile-time constant. Apply spec colors / sizes / radii verbatim — no rounding, but derive runtime layout from the artboard, parent constraints, and sibling relationships.
   10a. Every layout widget gets a leading `// …` comment in technical English: WHY this layout, WHY optimal vs the next-best alternative, citing `(#section)`, and which responsive geometry relation it implements (parent inset, sibling gap, stretch, proportional width, content size, or aspect ratio).
   10b. Every non-layout component gets the same kind of comment. For reused widgets, additionally cite the source `file:line` and state why reuse beats a fresh local widget while satisfying the responsive width/height modes.
   10c. No Chinese characters in any comment. No filler. One or two lines per comment. Comment must state a tradeoff the widget name itself does not convey.
   10d. Use `LayoutBuilder` or equivalent parent-constraint access whenever a value depends on the runtime container width/height. Do not compute responsive values from `MediaQuery` alone when the widget is nested inside a narrower parent.
   10e. Do not encode independent `left/top/width/height` constants for siblings that share an axis, gap, inset, or proportional rule. Encode the shared relationship once at the parent/group level.
   10f. Before creating any file or directory under `<root>/lib/`, verify the full relative path is ASCII-only and every new Dart filename is `lower_snake_case.dart`. If not, fix the slug before writing. Do not `mkdir` Chinese feature paths.
   10g. Do not implement anything outside the confirmed plan. If implementation reveals a layout/component decision that was not in the plan, STOP and return to step 8 with a revised plan.
11. **Run `flutter analyze {{OUTPUT_DIR}} {{COMMON_DIR}}`** from the project root (include `{{COMMON_DIR}}` only if step 10 wrote a new file there). Self-fix capped at 3 iterations. Do not advance until exit 0. If `flutter` is not on PATH → report `Verify: skipped: flutter not on PATH` and continue to step 12. Never fabricate the result.
12. **Run static visual-correctness check (verify-and-fix loop).**
    12a. Invoke `python3 ~/.agents/skills/fc/scripts/check_static.py --raw-json <spec_dir>/raw.json --code-dir {{OUTPUT_DIR}}`. Parse the one-line JSON.
    12b. Exit 0 → record `Check: matched/expected, exit 0` and proceed to step 13.
    12c. Exit 1 → for each entry in `mismatches`, edit the `.dart` at `file:line` to set the literal to `expected` (color → `Color(0x…)`, font_weight → `FontWeight.w<n>`, font_size → numeric, etc.). Fix the .dart, NEVER edit raw.json or spec.md. If the mismatched literal lives inside a reused widget at `<root>/lib/...`, do NOT edit the reused widget — wrap the call site with an override (e.g. `color:` argument, `Theme(...)`); the page must adapt to the shared widget, not vice versa.
    12d. For each entry in `unmatched_design`: locate the missing layer's intended position from the hierarchy tree (step 4) and add the corresponding widget. If the layer is genuinely decorative and ignorable, the user must explicitly mark it in spec.md as `# 视觉忽略: <layer_id>` — without that mark, treat it as a real defect.
    12e. After all edits, re-run `flutter analyze` (to catch syntax errors introduced by the edit), then re-run `check_static.py`. Loop 12c–12e up to 5 iterations total.
    12f. Still failing after 5 iterations → STOP with `Status: blocked` and surface the residual mismatches/unmatched_design list in the output. Do NOT continue to step 13.
    12g. Exit 2 → input error (raw.json unreadable / no .dart files). STOP with `Status: blocked` and the script's `error` field.
13. **Pause for final implementation review.** Emit `<output_format>`, then ask: `实现完成。请在 IDE 查看 diff 后确认是否进入下一阶段。` Wait for user.
</instructions>

<input>
- {{SPEC_PATH}}: absolute path to a `spec.md` produced by the `fd` skill.
- {{OUTPUT_DIR}}: derived in step 2 from `<root>/lib/<page-convention>/<feature_slug>/`. Caller does not supply unless step 2e/2f/2g prompts.
- {{COMMON_DIR}}: derived in step 2 from `<root>/lib/<common-convention>/`. Defaults to `<root>/lib/widgets/` if no convention exists.
</input>

<examples>
<example>
INPUT:
  SPEC_PATH = /repo/lanhu/specs/login_page/spec.md

ACTIONS:
- `pubspec.yaml` at `/repo`; `lib/pages/` exists → OUTPUT_DIR = `/repo/lib/pages/login_page/`. `lib/widgets/` exists → COMMON_DIR = `/repo/lib/widgets/`.
- spec.md: 4 layers at x=24..328, 16px vertical gap; one logo asset (slice on disk).
- Tree: Scaffold > SafeArea > Padding(24) > Column(spacing=16, crossAxis=stretch) > {Image, PhoneInputRow(Row), PasswordRow(Row), FilledButton, Center>TextButton}.
- `my-explore-0` reports: `lib/widgets/primary_button.dart:14 PrimaryButton({required Widget child, VoidCallback? onPressed})` — matches "primary CTA button" semantics. PhoneInputRow / PasswordRow not found.
- Sources: PrimaryButton → reused; PhoneInputRow → new-feature; PasswordRow → new-feature; logo Image / TextButton link → SDK inline.
- Sample comments in `login_page.dart`:
    // Scaffold: provides Material page skeleton with appBar/body/bottomSheet slots; (#3) — preferred over a bare Container because the design relies on Material insets and SnackBar surfaces.
    // SafeArea: insets content past the notch and gesture nav; (#3) — required for full-bleed login content on modern Android/iOS.
    // Padding(EdgeInsets.all(24)): applies the 24px outer gutter from spec; (#1, #11.4) — preferred over Container(padding:) since no decoration is needed.
    // Column(crossAxisAlignment: stretch): four siblings share x-range and stack with uniform 16px gap; (#1, #10.1) — Row would mismatch vertical layout, Wrap would lose ordering, ListView would over-engineer a fixed-count form.
    // Image.asset: ships the brand logo with the app bundle; (#4) — Image.network would add startup latency for a static asset.
    // PrimaryButton (lib/widgets/primary_button.dart:14): reused project CTA — matches the spec's primary button shape and brand fill; preferred over a fresh FilledButton to keep cross-page consistency.

OUTPUT:
Status:        ready-for-verify
Output dir:    detected /repo/lib/pages/login_page/
Common dir:    detected /repo/lib/widgets/
Files written: lib/pages/login_page/{login_page.dart, phone_input_row.dart, password_row.dart}
Reuse:         reused 1 (PrimaryButton @ lib/widgets/primary_button.dart:14); new-feature 2 (PhoneInputRow, PasswordRow); new-common 0
Hierarchy:     Scaffold > SafeArea > Padding > Column > {Image, PhoneInputRow, PasswordRow, PrimaryButton, Center>TextButton}
Rules applied: #1, #3, #4, #5, #6, #11.4
Slices:        none missing
Verify:        flutter analyze → 0
Check:         12/12, exit 0 (1 self-fix iter: btn font_weight w500 → w600 at login_page.dart:42)
Review:        (not requested yet)
</example>

<example label="BAD — do not do this">
Skip step 4. Guess hierarchy from layer names. Nested `SingleChildScrollView + Column` with `Expanded` children — `#11.1 + #11.3` violation that `flutter analyze` does not catch.
</example>

<example label="BAD — do not do this">
Slice missing, MCP unavailable. Substitute `Container(width: 80, height: 80, color: Colors.grey)` to keep `flutter analyze` green. P0 violation. Correct: STOP with `Slices: blocked: [<list>]`.
</example>

<example label="BAD — do not do this">
// 这是一个 Column，因为子组件需要垂直排列
Comment is in Chinese AND merely restates the widget name without rationale or section citation. Correct shape:
// Column(crossAxisAlignment: stretch): siblings share x-range and stack with uniform 16px gap; (#1, #10.1) — Wrap would lose ordering, ListView would over-engineer a fixed-count form.
</example>

<example label="BAD — do not do this">
`check_static.py` reports `mismatches: [{layer_id: t1, kind: color, expected: 0xFFFF5722, actual: 0xFFFF6633, file: login_page.dart, line: 42}]`. Agent edits `raw.json` to change the design color to `#FF6633` so the next check passes. P0 violation — design is the source of truth. Correct: edit `login_page.dart:42` to set the color to `Color(0xFFFF5722)`.
</example>

<example label="BAD — do not do this">
Skip step 7. Re-implement `PrimaryButton` locally as `LoginButton` with the same shape because "it's faster than searching". Project now has two buttons that drift over time. Correct: invoke `my-explore-0`, find the existing `PrimaryButton`, import + call.
</example>

<example label="BAD — do not do this">
`check_static.py` reports a color mismatch on a `PrimaryButton` instance. The `PrimaryButton` widget has a default fill that does not match this page's spec. Agent edits `lib/widgets/primary_button.dart` to change the default fill so the page passes — silently breaking every other page using `PrimaryButton`. P0 violation. Correct: leave the reused widget untouched; pass `color:` (or wrap with `Theme(...)`) at the call site so only this page sees the override.
</example>
</examples>

<plan_review_format>
Status:        plan-review
Output dir:    `detected <path>` | `asked-and-supplied <path>`
Common dir:    `detected <path>` | `defaulted <path> (will be created on first reusable widget)`
Names:         `design "<design_name>" → feature_slug "<feature_slug>"` | `fallback screen_<image_id8>`
Visual tree:   one-line abstract visual hierarchy, e.g. `Page → AppBar → ContentList → StatusCard[]`
Geometry:      design `<w>x<h>`; modes summary, e.g. `root stretch, hero aspect-ratio, cards proportional, list content`
Layout plan:   parent/group layout choices with `flutter-widget.md` section numbers
Components:    proposed components with source classification: `reused | new-common | new-feature | sdk-inline`
Reuse:         `reused <n> (<name> @ <file:line>, …); new-common <n> (<names>); new-feature <n> (<names>)`
Files planned: proposed ASCII `lower_snake_case.dart` paths only; no files written yet
Ambiguities:   `none` | concise list requiring user decision
Question:      `是否有布局或组件拆分建议？确认后我再开始实现代码。`
</plan_review_format>

<output_format>
Status:        ready-for-verify | blocked
Output dir:    `detected <path>` | `asked-and-supplied <path>`
Common dir:    `detected <path>` | `defaulted <path> (will be created on first reusable widget)`
Names:         `design "<design_name>" → feature_slug "<feature_slug>"` | `fallback screen_<image_id8>`
Files written: <path>/<file>.dart → one-line description, one per line (group by output-dir / common-dir)
Reuse:         `reused <n> (<name> @ <file:line>, …); new-common <n> (<names>); new-feature <n> (<names>)`
Hierarchy:     one-line widget tree (root → leaves)
Geometry:      design `<w>x<h>`; modes summary, e.g. `root stretch, hero aspect-ratio, cards proportional, list content`
Rules applied: section numbers, e.g. `#1, #10.1, #11.4`
Slices:        `none missing` | `<n> fetched: <paths>` | `blocked: <missing>`
Plan review:   accepted | accepted-after-changes
Verify:        `flutter analyze → 0` | `flutter analyze → N issues: <summary>` | `skipped: flutter not on PATH`
Check:         `<matched>/<expected>, exit 0` | `blocked after <n> iters: <m> mismatches, <k> unmatched_design`
Review:        accepted | accepted-after-changes | (not requested yet)
</output_format>

<success_criteria>
Complete when ALL hold:
- spec.md fully read; hierarchy tree produced.
- Design artboard size captured; every non-root node has parent/sibling context and width/height mode recorded before code is written.
- `{{OUTPUT_DIR}}` and `{{COMMON_DIR}}` resolved (auto-detected, defaulted, or user-supplied).
- `{{OUTPUT_DIR}}`, every new directory, every Dart filename, and every Dart identifier created by this run is ASCII-only; feature and widget files use English `lower_snake_case`.
- Step 7 reuse search invoked via `my-explore-0`; every non-leaf node classified as `reused | new-common | new-feature`.
- Step 8 plan review emitted before any `lib/` directory creation or Dart write; user explicitly confirmed the visual hierarchy, component split, and Flutter layout plan.
- Every non-leaf widget cites a `flutter-widget.md` section number.
- Every layout widget AND every component carries an English `// …` rationale comment per step 10 with `(#section)` and responsive geometry rationale. Reused-widget comments additionally cite `file:line` of the reused source.
- No isolated absolute `x/y/w/h` implementation exists unless justified by overlap, decorative artwork, or an explicitly fixed artboard-relative element.
- Parent/group-level constraints encode shared sibling gaps, alignment, proportional sizing, stretch, content sizing, and aspect ratio before child dimensions are assigned.
- No Chinese characters in any code comment.
- No `#11` anti-pattern present in written code.
- No reused widget under `<root>/lib/` was edited by this run (reused widgets stay untouched).
- Every referenced slice exists on disk, OR run reported `Status: blocked` with the list.
- `flutter analyze` exits 0, OR reported `skipped: flutter not on PATH`.
- `check_static.py` exits 0 (matched == expected, no mismatches, no unmatched_design), OR run reported `Status: blocked` with the residual list after 5 iterations.
- User asked for final implementation review (step 13).
Stop the moment those hold. Do not run tests, edit pubspec, or touch theme / router unilaterally.
</success_criteria>

<final_reminders>
P0 — Never fabricate `flutter analyze` results.
P0 — Never substitute a placeholder for a missing slice. Fetch via `mcp__lanhu__lanhu_get_design_slices` or report `Status: blocked`.
P0 — Never violate any `flutter-widget.md` `#11` anti-pattern.
P0 — Never implement layer bbox coordinates or width/height as isolated absolute values. Runtime layout must be derived from design artboard size + parent constraints + sibling relationships. Raw `Positioned` constants are allowed only for proven overlap/decorative/fixed-artboard cases with an explicit comment.
P0 — Never let child widgets scale independently from their own bboxes when they belong to a component group. Calculate the group first, then derive children from parent insets, sibling gaps, proportional/stretch/content modes, and aspect ratio.
P0 — Never create Flutter implementation directories, Dart files, imports, class names, or identifiers using Chinese, pinyin, spaces, hyphens, punctuation, or any non-ASCII character. `lanhu/specs/<design_name>/` may be Chinese; `<root>/lib/...` must be semantic English ASCII.
P0 — Never expand scope beyond `{{OUTPUT_DIR}}` ∪ `{{COMMON_DIR}}`. Pubspec / theme / router / new dependency requires explicit user OK.
P0 — Never read `flutter-widget.md` or `raw.json` in full. Targeted reads only.
P0 — All `raw.json` queries go through `~/.agents/skills/fc/scripts/inspect_layers.py`. NEVER write inline Python / `jq` / `grep` against raw.json — the wrapper schema is `figma_json.artboard`, and ad-hoc queries that read `raw["artboard"]` silently see zero layers and pass falsely.
P0 — Every layout widget AND every component carries a leading `// …` comment in idiomatic technical English explaining WHY this widget and WHY it is optimal vs the next-best alternative, citing `(#section)`. Reused widgets additionally cite `file:line`. No Chinese characters in any code comment. No filler. Removing the comment must lose information.
P0 — Step 2 detects `{{OUTPUT_DIR}}` and `{{COMMON_DIR}}` from the project; ask the user only when 2e (no page convention), 2f (non-ASCII path), or 2g (already populated) triggers. Do not invent a path.
P0 — Step 7 reuse search via `my-explore-0` is mandatory for every non-leaf node. Re-implementing a project widget that already covers the role is forbidden — use `my-explore-0` first, classify every node as `reused | new-common | new-feature`. Do NOT use raw shell reads on source for this search; per project memory, code exploration goes through `my-explore-0`.
P0 — Step 8 plan review is mandatory before code implementation. Do not create `{{OUTPUT_DIR}}`, create common widgets, or write/edit any Dart file until the user has reviewed the visual hierarchy, component split, Flutter layout plan, and explicitly confirmed.
P0 — Never edit a reused widget under `<root>/lib/` to make this page's check pass. Cosmetic divergence is resolved by overriding at the call site (constructor args, `Theme(...)` wrap), not by mutating the shared source. Mutating shared widgets is a regression bomb for every other page that imports them.
P0 — Never auto-promote an existing feature-specific widget into `{{COMMON_DIR}}`. That is a refactor, out of scope; surface the candidate to the user instead.
P0 — When `check_static.py` reports a mismatch, fix the `.dart` at the reported `file:line` to match raw.json. NEVER edit raw.json or spec.md to make the check pass — that inverts the source of truth.
P0 — Step 12 verify-and-fix is mandatory. Do not advance to step 13 (final implementation review) on a non-zero check exit unless 5 iterations have been exhausted and `Status: blocked` is reported.
P1 — Step 4 precedes step 7. Step 6 (SDK widget pick) precedes step 7 (project reuse search). Step 7 precedes step 8 (plan review). Step 8 user confirmation precedes step 10 (write).
P1 — Reuse-vs-new judgment defaults to feature dir when uncertain. New-common requires confidence the widget is generic and will recur on ≥2 pages.
P1 — Edit existing files in place; create only genuinely new files.
P1 — `Padding` not `Container(padding:)` (#11.4). `const` where applicable. Spec values verbatim.
P1 — Prefer `LayoutBuilder`, `Expanded`, `Flexible`, `AspectRatio`, `FractionallySizedBox`, `Align`, `Padding`, and `ConstrainedBox` when they encode the responsive geometry plan more directly than hard-coded dimensions.
P2 — Repeated arrangements within one page → one widget + `.map`. No paste-copy.
</final_reminders>
