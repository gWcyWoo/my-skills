---
name: url_lanhud
description: Export all design viewer links from a Lanhu UI project to Markdown and CSV.
---

# url_lanhud

Enumerate every design draft in a Lanhu UI design project as standalone `detailDetach` viewer URLs, written to disk as Markdown and CSV. The job ends with two verified files; do not analyze design content in this skill.

## Inputs

Accept either:

- A Lanhu UI design project URL with `tid` and `pid` parameters and **no** `docId`. Example: `https://lanhuapp.com/web/#/item/project/stage?tid=...&pid=...`. If it is an invite link, resolve it first with `lanhu_resolve_invite_link`.
- An already-cached `lanhu_get_designs` JSON response and the originating project URL.

If neither is provided, ask the user for exactly one thing: `请提供蓝湖 UI 设计项目地址（含 tid+pid，不含 docId）。`

If the URL contains `docId=`, refuse: it is a PRD/Axure prototype, not a UI design project. Tell the user to use the PRD-oriented skill instead.

## Workflow

1. Locate the project root with `git rev-parse --show-toplevel`; if that fails, use the current working directory. Ensure `lanhu/links/` exists.
2. Validate URL shape. The URL must contain both `tid=` and `pid=`. Extract `pid`. Reject the URL if `docId=` is present.
3. Fetch the design list with `lanhu_get_designs(url)`. Capture `project_name`, `total_designs`, and the full `designs[]` array. Each entry must have `index`, `id`, `name`.
4. For every design, format the viewer URL exactly as:

   ```
   https://lanhuapp.com/web/#/item/project/detailDetach?pid={pid}&project_id={pid}&fromEditor=true&image_id={design.id}
   ```

   `pid` and `project_id` are the same value; copy `pid` into both. Do not substitute the design's `url` field (a `FigmaCover*.png` thumbnail) for the viewer link.
5. Write two files at `lanhu/links/{safe-project-name}.md` and `lanhu/links/{safe-project-name}.csv`. Replace path separators and unsafe filename characters in the project name with `-`.
6. Report the project name, verified count, and both file paths. Include a short preview only when useful.

## Output Format

### Markdown — `lanhu/links/{safe-project-name}.md`

```markdown
# {project_name} — 设计稿链接（共 {total_designs}）

源项目: {input_url}
生成时间: {ISO-8601 timestamp with timezone}
来源: lanhu_get_designs

1. **{name}** — {detailDetach_url}
2. **{name}** — {detailDetach_url}
...
```

Preserve original Chinese names from Lanhu. Keep entries in the order returned by `lanhu_get_designs` (sorted by `index`).

### CSV — `lanhu/links/{safe-project-name}.csv`

Header row exactly:

```
index,name,image_id,url
```

One row per design. Quote the `name` field with double quotes; escape embedded double quotes by doubling them (`"` → `""`). Do not URL-encode the `url` column.

### Rules

- Preserve `pid` and `image_id` exactly as Lanhu returned them; do not lowercase or reformat UUIDs.
- If `lanhu_get_designs` returns 0 designs, write empty files with only the header/title and report that the project is empty; do not invent rows.
- If a health check blocks MCP access, report its actual error and diagnose the configured transport. Do not forge a healthy cache entry or bypass the check.
- Never paste more than 10 rows into the chat response; the files are the deliverable.
