---
name: self-check
description: Generic independent review skill. Dispatches a strict reviewer agent to verify artifacts against caller-provided rules. Reusable across understand, testcase, code phases.
---

# Independent Self-Check

Generic review framework. The caller provides:
1. **Files to review** — the artifacts to verify
2. **Rules file** — what to check (tables, criteria, evidence format)
3. **Output path** — where to write the review result

This skill dispatches an independent reviewer agent that reads the actual files and fills checklist tables with quoted content evidence. The reviewer is NOT the author — it has no loyalty to the documents.

## Parameters

When invoking this skill, the caller must provide:
- `procedure_dir` — the procedure directory path
- `rules_path` — absolute path to the self-check rules file (e.g., `~/.claude/skills/understand/self-check.rules.md`)
- `files` — list of files to review (e.g., `requirement.md, understand.md, hld.md`)
- `output_path` — where to write the review (e.g., `{procedure_dir}/audit/self-check.md`)

## Process

### Step 1: Dispatch Reviewer Agent

Launch an Agent subagent (superpowers:code-reviewer or general-purpose) with this prompt:

```
You are a strict, adversarial reviewer. Your job is to find every defect by reading actual files and filling checklist tables with quoted content evidence.

RULES (read first — defines what to check and output format):
{rules_path}

FILES TO REVIEW:
{list of file paths}

OUTPUT:
Write the complete review to {output_path}

CRITICAL PRINCIPLE: Every table cell that references a document element must QUOTE the actual text from the file. ID-only references are forbidden — if you can't quote the content, the element doesn't exist. This prevents fabrication.

After completing the review:
- If all tables are clean: return STATUS: PASS
- If any table has ❌ rows: return STATUS: ISSUES_FOUND with count and categories
```

### Step 2: Handle Result

- **STATUS: PASS** — Return to caller with PASS
- **STATUS: ISSUES_FOUND** — Return to caller with the issues. The caller is responsible for fixing and re-dispatching this skill.
