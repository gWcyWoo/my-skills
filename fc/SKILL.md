---
name: fc
description: Use when implementing Flutter UI from a Lanhu-derived spec.md path or directory. Triggers on "fc", "flutter 实现", "蓝湖→Flutter".
---

<role>
Convert one Lanhu-derived `spec.md` into responsive Flutter UI code. Produce a visual hierarchy, component plan, and layout plan; get user confirmation before writing Dart code.
</role>

<context>
Rule files:
- `~/.agents/skills/fc/development_rules.md`
- `~/.code/shared-rules/frontend/flutter-widget.md`

Use `development_rules.md` as higher-priority project guidance. If it conflicts with `flutter-widget.md`, `development_rules.md` wins.

Use `flutter-widget.md` only through exact `FW-*` ID reads.

Do not read it fully. Do not query multiple `FW-*` IDs or `FW-*` prefixes in one command. First discover only headings/rule IDs:

```bash
rg -n "^#{1,3} .*\\[FW-" ~/.code/shared-rules/frontend/flutter-widget.md
```

Then read only exact individual rule IDs for decisions not resolved by `development_rules.md`:

- Read `development_rules.md` first. If a `DEV-*` rule resolves the decision, do not query `flutter-widget.md` for the same decision.
- One `flutter-widget.md` query must contain exactly one `FW-*` ID.
- Use exact ID lookup only, for example:
  `rg -n -A 20 -B 2 "\\[FW-LAYOUT-COLUMN\\]" ~/.code/shared-rules/frontend/flutter-widget.md`
- Do not use alternation, prefix, wildcard, heading-number, or family queries such as `FW-LAYOUT-*`, `FW-ANTI-*`, `FW-LAYOUT-COLUMN|FW-LAYOUT-ROW`, `#10`, or `#11`.
- During plan review, read at most 5 individual `FW-*` rules total. During implementation, read an additional exact ID only when a decision was not present during plan review.
- Cite `FW-*` only for exact rules actually read.

Each component, layout, size, and asset decision must be checked against `development_rules.md` before plan review. Record applicable `DEV-*` IDs or `无直接适用规则`. If a decision would violate a `DEV-*` rule, reject it and choose a compliant alternative. If no compliant alternative exists or the spec/user explicitly requires the violation, keep it only as a `DEV 例外` and record the violated rule, violation reason, risk, mitigation, and required user confirmation. Cite `FW-*` only when an exact `FW-*` rule was read.

Raw layer inspection:
- `raw.json` is sibling of `spec.md`
- Use only to resolve ambiguities from `spec.md`
- Never bulk-read `raw.json`
- Never use inline Python, jq, grep, cat, sed against raw.json

Allowed raw query:

```bash
python3 ~/.agents/skills/fc/scripts/inspect_layers.py --raw-json <path> [--ids ID,ID] [--type textLayer|shapeLayer|groupLayer|artboard] [--name-contains SUBSTR]
```

Static check:

```bash
python3 ~/.agents/skills/fc/scripts/check_static.py --raw-json <spec_dir>/raw.json --code-dir {{OUTPUT_DIR}} [--font-scale {{PT_SCALE}}]
```

Project root:
- nearest ancestor of spec.md or cwd containing `pubspec.yaml`

Page output convention, first existing:
1. `lib/pages/<feature_slug>/`
2. `lib/features/<feature_slug>/presentation/`
3. `lib/screens/<feature_slug>/`
4. `lib/views/<feature_slug>/`

Common widget convention, first existing:
1. `lib/widgets/`
2. `lib/components/`
3. `lib/shared/widgets/`
4. `lib/common/widgets/`
5. default `lib/widgets/`, created only if writing common widgets

Naming:
- Generated paths under `lib/` must be ASCII only
- Dart files: `lower_snake_case.dart`
- Classes: ASCII `UpperCamelCase`
- No Chinese paths, filenames, identifiers, imports, parts, or code comments
- If Chinese design name cannot be semantically translated, use `screen_<image_id8>`
</context>

<hard_rules>
- Do not write Dart or create `lib/` directories before user confirms the plan
- Do not full-read `flutter-widget.md`
- Do not bulk-read `raw.json`
- Do not modify reused project widgets
- Do not edit `spec.md` or `raw.json`
- Do not touch pubspec, theme, router, or dependencies without explicit user approval
- Do not implement outside the confirmed plan
- Do not use Chinese in generated code comments
- Do not create non-ASCII paths or identifiers under `lib/`
- Do not use raw absolute `Positioned(left/top/width/height)` unless overlap/decorative/fixed-artboard evidence exists
- Do not implement `SingleChildScrollView + Column + large dynamic children`
- Do not put `Expanded` outside `Row` / `Column` / `Flex`
- Do not put `Expanded` in scroll-direction `Column` under `SingleChildScrollView`
- Do not distort image/icon/slice aspect ratio unless explicit stretch evidence exists
</hard_rules>

<workflow>
1. Resolve `{{SPEC_PATH}}`
   - If input is a directory, append `/spec.md`
   - If missing, stop: `spec.md not found at <path>`

2. Detect project root, output dir, common dir
   - Find nearest `pubspec.yaml`
   - Derive English ASCII `<feature_slug>`
   - Pick page/common dirs by convention
   - If page convention missing, ask for absolute ASCII output dir
   - If output dir already contains Dart files, ask: overwrite, append, or different path

3. Read `spec.md` fully

   Capture:
   - design URL
   - design name
   - image_id
   - artboard width/height
   - layer list
   - bbox
   - text
   - font size/weight
   - colors
   - radius/border
   - asset paths

   Do not touch `raw.json` yet

4. Derive visual hierarchy from `spec.md` before component or layout design

   Produce:

   ```text
   Page → Section → Item → Atom
   ```

   For each meaningful visual node record:
   - semantic role
   - visual priority
   - parent
   - sibling group
   - axis
   - gap
   - overlap evidence
   - repeated-pattern evidence
   - enclosing-background evidence
   - design-size evidence from `spec.md`
   - preliminary constraint hint: `fixed | content | stretch | proportional | aspect-ratio`
   - unresolved ambiguities

5. Resolve only necessary ambiguities with `inspect_layers.py`
   - Batch IDs from the same ambiguity group
   - Do not inspect unrelated raw layers

6. Design strictly in this order:
   1. Use the visual hierarchy from step 4 as the source of truth.
   2. Design component responsibilities and boundaries from the visual hierarchy.
   3. Design Flutter layout from the component tree.
   4. Validate geometry through parent/child and sibling constraints together.
   5. Reject anti-patterns and record unresolved ambiguities.

   Rule lookup procedure:
   - Read `~/.agents/skills/fc/development_rules.md` before `flutter-widget.md`.
   - Apply `DEV-*` rules first; cite relevant `DEV-*` IDs in the plan.
   - For every component boundary, page scaffold slot, layout choice, size conversion, scroll decision, bottom persistent area, and asset choice, run a `DEV 检查`.
   - `DEV 检查` must list applicable `DEV-*` IDs and the compliance result, or `无直接适用规则`.
   - If `DEV 检查` finds a violation, reject that choice and record the compliant alternative.
   - If a violation is unavoidable or explicitly required, record `DEV 例外`: violated rule ID, why it must violate, risk, mitigation, and confirmation needed.
   - Start with heading/rule discovery only:
     `rg -n "^#{1,3} .*\\[FW-" ~/.code/shared-rules/frontend/flutter-widget.md`
   - Before reading any `FW-*` rule, name the single unresolved design decision.
   - Read one exact `FW-*` ID per command:
     `rg -n -A 20 -B 2 "\\[FW-EXACT-ID\\]" ~/.code/shared-rules/frontend/flutter-widget.md`
   - Do not query multiple IDs, wildcard families, prefixes, section numbers, or headings to pull whole sections.
   - Do not read `#0`, `#10`, `#11`, or `#13` by default.
   - During plan review, stop after at most 5 exact `FW-*` rule reads.
   - If `development_rules.md` already covers the decision, skip `flutter-widget.md` for that decision.

   Component design requirements:
   - Map each component to one or more visual hierarchy nodes.
   - Define the component responsibility before choosing Flutter layout widgets.
   - Choose `reused`, `new-common`, `page-local`, or `sdk-inline` as a provisional source; step 7 finalizes it after reuse search.
   - Similar/repeated elements used only inside this page stay `page-local` in the same Dart file.
   - Check each component boundary against `DEV-COMPONENT-PAGE-LOCAL` and `DEV-COMPONENT-COMMON`.
   - Record the layout constraints the component requires or exposes, but do not implement yet.

   Layout design requirements:
   - Choose the overall page layout from the confirmed component tree.
   - Check the page root against `DEV-PAGE-SCAFFOLD`.
   - Check top navigation/title/back/close/actions against `DEV-PAGE-APPBAR`.
   - Check scroll-body decisions against `DEV-PAGE-SCROLL-BODY`.
   - Check persistent bottom content against `DEV-BOTTOM-PERSISTENT`.
   - Prefer linear layout (`Row`/`Column`) before `Stack`/`Positioned`.
   - Check each `Row`/`Column`/`Stack`/`Positioned` choice against `DEV-LAYOUT-LINEAR-FIRST` and `DEV-LAYOUT-STACK-ADAPTIVE`.
   - For each component, design parent layout, child layout, and sibling spacing together.
   - Record width mode: `fixed | content | stretch | proportional | aspect-ratio`.
   - Record height mode: `fixed | content | stretch | proportional | aspect-ratio`.
   - Record runtime constraint strategy for responsive/adaptive behavior.
   - Use design artboard size only as the conversion baseline, not as a fixed screen size.
   - Check width/height and artboard use against `DEV-RESPONSIVE-PAGE`.
   - Check text, spacing, radius, border, icon, image, and explicit visual sizes against `DEV-UNITS-IOS-PT`.
   - Check background image, icon, and logo asset choices against `DEV-ASSETS-WEBP-2X`.

   For each non-leaf component create a compact decision:
   - node name
   - responsibility
   - spec evidence
   - mapped visual hierarchy node
   - component source
   - `DEV 检查`
   - `DEV 例外` when applicable
   - geometry mode
   - chosen widget/layout
   - cited `DEV-*` rule when applicable
   - cited exact `FW-*` rule when read
   - rejected alternative
   - anti-pattern risk and mitigation
   - reuse-search role

7. Search project reuse

   Follow the active `AGENTS.md` source-exploration rules. Search `<root>/lib/` for all candidate roles in one pass.

   Request:
   - file:line
   - class name
   - constructor signature
   - visual semantics
   - import path

   Classify each non-leaf node:
   - `reused`
   - `new-common`
   - `page-local`
   - `sdk-inline`

   Reuse only if signature and visual semantics match

   Classification rules:
   - `page-local`: similar/repeated elements used only inside this page; extract as private widgets/classes in the page Dart file, not separate files.
   - `new-common`: same functional component is used widely in the project or clearly expected across pages; create one common widget file after plan confirmation.
   - If uncertain, choose `page-local`.

8. Emit plan review and stop
   - Do not write files
   - Ask the user to review visual hierarchy, component boundaries, and layout

9. After explicit confirmation, resolve missing slices
   - List asset paths missing on disk
   - Fetch only referenced missing slices through Lanhu MCP
   - Save to `<spec_dir>/assets/`
   - If unavailable, stop with `Status: blocked`

10. Write Dart files

   10a. Scope:
   - `{{OUTPUT_DIR}}`
   - `{{COMMON_DIR}}`

   10b. Add file header:

   ```dart
   // Generated by fc from Lanhu spec.
   ```

   10c. Use `const` where possible

   10d. Use file-local constants for repeated visual literals

   10e. Preserve static-check-visible literals

   10f. Use parent/group constraints instead of independent bbox scaling

   10g. Add English `// fc:` comments only for:
   - key layout decisions
   - responsive decisions
   - raw positioning
   - reused widget calls
   - anti-pattern avoidance

   10h. If a new decision appears, stop and return to plan review

11. Format and analyze

   11a. Run `dart format` on files written by this run

   11b. Run:

   ```bash
   flutter analyze {{OUTPUT_DIR}} {{COMMON_DIR}}
   ```

   from project root

   11c. Include `{{COMMON_DIR}}` only if common files were written

   11d. Self-fix analyze errors up to 3 iterations

   11e. If tools missing, report skipped honestly

12. Run static visual check

   12a. Run `check_static.py`; if `DEV-UNITS-IOS-PT` applies, pass `--font-scale {{PT_SCALE}}`

   12b. If mismatches, fix generated Dart literals only

   12c. If reused widget mismatch, override at call site

   12d. If unmatched design, add corresponding widget unless spec marks it ignored

   12e. Loop up to 5 iterations

   12f. If still failing, stop with `Status: blocked` and residual list
</workflow>

<plan_review_format>
状态:          plan-review

输出目录:      `detected <path>` | `asked-and-supplied <path>`

公共组件目录:  `detected <path>` | `defaulted <path>`

命名:          `design "<design_name>" → feature_slug "<feature_slug>"` | `fallback screen_<image_id8>`

设计尺寸:      `<width>x<height>`

视觉层次:
1. `<Page/Section/Item/Atom>` — `<语义角色>`
   - 优先级: `<主要 | 次要 | 辅助>`
   - 父级: `<父级或无>`
   - 同级关系: `<轴向/间距/对齐>`
   - 设计证据: `<spec.md 证据>`
   - 约束提示: `<fixed | content | stretch | proportional | aspect-ratio>`

组件设计:
1. `<PageComponent>`
   - 对应视觉层次: `<视觉节点>`
   - 职责: `<页面职责>`
   - 来源: `<page-local | reused | sdk-inline>`
   - 对外约束: `<尺寸/滚动/交互约束>`
   - DEV 检查: `<通过 DEV-* | 违反 DEV-*：原因/风险/缓解/需确认 | 无直接适用规则>`
   - 子组件:
     1.1 `<ChildComponent>`
        - 对应视觉层次: `<视觉节点>`
        - 职责: `<职责>`
        - 来源: `<reused | new-common | page-local | sdk-inline>`
        - 对外约束: `<约束>`
        - DEV 检查: `<通过 DEV-* | 违反 DEV-*：原因/风险/缓解/需确认 | 无直接适用规则>`
        - 子组件: `<子组件或无>`

布局设计:
1. `<PageComponent>` — `<Scaffold/SafeArea/LayoutBuilder/ScrollView/...>`（`DEV-*` 如适用；`FW-*` 仅在已读取精确规则时标注）
   - Scaffold 槽位: appBar `<used | not-used | n/a>`，body `<used>`，bottomNavigationBar `<used | not-used | n/a>`
   - 整体布局: `<布局和理由>`
   - 子布局: `<子组件排列方式>`
   - 几何: 宽度 `<mode>`，高度 `<mode>`，策略 `<父子/兄弟约束策略>`
   - 组件选择: 选择 `<widget>`，不选 `<alternative>`，因为 `<evidence>`（`DEV-*` 如适用；`FW-*` 仅在已读取精确规则时标注）
   - DEV 检查: `<通过 DEV-* | 违反 DEV-*：原因/风险/缓解/需确认 | 无直接适用规则>`
   - 子布局:
     1.1 `<ChildComponent>` — `<Column/Row/Stack/ListView/...>`（`DEV-*` 如适用；`FW-*` 仅在已读取精确规则时标注）
        - 几何: `<inset/gap/stretch/content/proportional/aspect-ratio>`
        - 组件选择: `<选择和理由>`（`DEV-*` 如适用；`FW-*` 仅在已读取精确规则时标注）
        - DEV 检查: `<通过 DEV-* | 违反 DEV-*：原因/风险/缓解/需确认 | 无直接适用规则>`
        - 子布局: `<子布局或无>`

复用:
- reused `<n>`: `<name> @ <file:line>`
- new-common `<n>`: `<names>`
- page-local `<n>`: `<names>`
- sdk-inline `<n>`: `<roles>`

已排除反模式:
- `<node>` 排除 `<anti-pattern>`，因为 `<evidence>`；选择 `<alternative>`（`FW-*` 仅在已读取精确规则时标注）
- `无`

DEV 例外:
- `无` | `<node>` 违反 `<DEV-*>`：原因 `<why>`；风险 `<risk>`；缓解 `<mitigation>`；需用户确认 `<yes>`

计划文件:
- `<ASCII lower_snake_case.dart paths>`
- 尚未写入文件

缺失切图:
- `无` | `<asset 路径>`

待确认问题:
- `无` | `<简要列表>`

问题:
我已根据 spec.md 按“视觉层次 → 组件设计 → 布局设计”的顺序完成方案。请审核：视觉层次、组件边界或布局是否需要调整？确认后我再开始实现代码。
</plan_review_format>

<success_criteria>
- plan confirmed before code
- output/common dirs resolved
- spec fully read
- visual hierarchy, component boundaries, and layout tree recorded in order
- parent/child and sibling geometry modes recorded
- `development_rules.md` read and higher-priority `DEV-*` rules applied
- `flutter-widget.md` read only by exact `FW-*` ID when needed
- reuse search completed
- key widget decisions cite applicable `DEV-*`; cite `FW-*` only when read
- every component/scaffold-slot/layout/size/asset decision has `DEV 检查`
- any `DEV-*` violation is either rejected or recorded as `DEV 例外` with reason, risk, mitigation, and user confirmation requirement
- generated code uses ASCII paths/identifiers/comments
- reused project widgets unchanged
- no unplanned files changed
- no known anti-pattern present
- referenced slices exist or blocked reported
- `dart format` run or skipped with reason
- `flutter analyze` passes or skipped with reason
- `check_static.py` passes or blocked reported after allowed fixes
</success_criteria>
