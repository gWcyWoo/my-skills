---
name: fd
description: Use when converting one or more Lanhu UI designs into frontend development specs, especially requests mentioning fd, 前端开发, 蓝湖设计稿, 批量解析设计稿, 设计稿转开发文档, lanhu/specs, or Chrome DevTools UI-data verification.
---

# FD

Convert Lanhu UI designs into precise frontend development specs. The job ends with verified Markdown specs; do not implement frontend code in this skill.

## Inputs

Accept either:

- A Lanhu UI design URL. If it is an invite link, resolve it first with `lanhu_resolve_invite_link`.
- An existing `lanhu/specs/*.md` file generated from Lanhu.

If neither is provided, ask the user for exactly one thing: `请提供蓝湖设计稿地址，或已生成的 lanhu/specs/*.md 路径。`

If a provided spec lacks the source design URL/name or lacks exact UI values, treat it as incomplete and ask for the Lanhu design URL before continuing.

## Workflow

1. Locate the project root with `git rev-parse --show-toplevel`; if that fails, use the current working directory. Ensure `lanhu/specs/` exists.
2. Select the design set. For a Lanhu UI project URL, call `lanhu_get_designs` first. If the user asks for all designs or batch parsing, select every design returned by Lanhu. If the URL or list clearly identifies one design, use it. If multiple designs are plausible and the user did not request all, ask the user for design names or indexes.
3. Process the selected designs in a loop, one design at a time. For each design, extract it with `lanhu_get_ai_analyze_design_result(url, design_names=...)`. Use the returned HTML+CSS as the primary source of truth. Use the returned design image only as visual verification. Call `lanhu_get_design_slices` when icons, image assets, or slice metadata are missing or ambiguous.
4. Write one Markdown file per design at `lanhu/specs/{safe-design-name}.md`. Keep Chinese design names when useful; replace path separators and unsafe filename characters with `-`.
5. Verify each generated spec with Chrome DevTools before moving to the next design. If Chrome DevTools tooling is unavailable, stop and report that verification is blocked; do not claim the current or remaining specs are complete.
6. Continue the loop until every selected design has a generated and verified spec, or until a blocking issue prevents safe verification.
7. Final response must include only the batch summary: processed count, skipped or blocked designs, each spec path, and Chrome verification status for each design.

## Spec Format

The generated Markdown must have exactly these four H2 sections in this order:

```markdown
# {design_name} 前端开发文档

## 文档描述

## UI描述

## 交互

## 数据
```

### 文档描述

Include source and verification metadata:

- Lanhu URL
- Design name or index
- Generation timestamp with timezone
- Source MCP calls used
- Asset handling notes
- Chrome DevTools verification record: viewport, inspected fixture/page, number of elements checked, mismatches corrected, unresolved blockers

### UI描述

Use only exact design data. Do not write broad descriptions such as "large title", "blue button", "centered card", or "spacing is generous". Every visible element must be represented by exact values from Lanhu HTML+CSS and Chrome computed data.

Required data:

- Artboard: width, height, background, pixel ratio when available.
- Element inventory: stable element id/selector, hierarchy, text/resource, absolute `x`, `y`, `width`, `height`, display/position, opacity, overflow, z-index.
- Typography: font-family, font-size, font-weight, line-height, letter-spacing, text-align, color, text content.
- Box model: margin, padding, border, border-radius, shadow, background, gradients, clipping.
- Assets: local asset path, rendered size, natural size when available, object-fit/background-size, opacity.
- Repeated lists: document one component template with exact style values plus a per-instance table for coordinates, text, and asset differences.

Rules:

- Preserve units and value formats exactly, including `px`, `rgba(...)`, decimals, gradients, and shadow strings.
- Use the artboard top-left as `(0, 0)`. If Lanhu provides nested coordinates, record both parent-relative and absolute coordinates.
- If a value is not provided by Lanhu or Chrome, write `未提供`; never infer or guess.
- Do not omit visible elements. If something is intentionally excluded, record the reason in the Chrome verification record.

### 交互

Reserve this section for developers. Do not invent behavior from the UI.

Use this placeholder:

```markdown
> 待开发人员填写。请在后续需求确认阶段补充点击、输入、跳转、弹窗、加载、空态、错误态、权限态等交互规则。
```

### 数据

Reserve this section for developers. Do not invent APIs, fields, or storage rules.

Use this placeholder:

```markdown
> 待开发人员填写。请在后续需求确认阶段补充数据来源、接口、字段映射、枚举、默认值、分页、缓存、刷新和异常处理规则。
```

## Chrome Verification

Create or open a temporary verification page that renders the Lanhu-returned HTML+CSS with local assets. Use Chrome DevTools to inspect computed layout and style.

Check each documented element:

- DOM/text/resource presence matches the Lanhu output.
- Bounding rect matches documented `x`, `y`, `width`, and `height`.
- Computed typography matches documented font family, size, weight, line-height, letter-spacing, alignment, and color.
- Computed box style matches background, gradient, border, radius, shadow, opacity, overflow, and clipping.
- Image elements use local asset paths and match rendered dimensions.
- The rendered screenshot visually matches the Lanhu design image; image comparison is secondary to HTML+CSS and computed styles.

When any mismatch is found, fix `lanhu/specs/{safe-design-name}.md` and re-check the affected element. The final spec must record what was corrected under `## 文档描述`.
