---
name: sync
description: Manage and sync shared rules to project CLAUDE.md
arguments:
  - name: action
    description: "Rule name to sync, or 'write <name> <content>', or 'list'"
    required: false
---

# Sync Shared Rules

Central rule repository at `~/.claude/shared-rules/`. Rules here are NOT auto-loaded — they must be explicitly synced to a project's CLAUDE.md.

## Commands

### `/sync list`
List all available rules in `~/.claude/shared-rules/`.
- Read the directory listing
- Display each rule name (filename without .md extension) and its first line as description
- Format as a clean table

### `/sync write <rule-name> <content>`
Write or update a rule in the central repository.
- File path: `~/.claude/shared-rules/<rule-name>.md`
- If the file exists, show current content and ask user to confirm overwrite
- If new, create the file with the provided content
- Content should be valid Markdown that can be appended to a CLAUDE.md

### `/sync <rule-name>`
Sync a specific rule into the current project's CLAUDE.md.
- Read `~/.claude/shared-rules/<rule-name>.md`
- If file not found, show error and run `/sync list` to help user
- Read the current project's CLAUDE.md (find the nearest CLAUDE.md in current working directory or parent directories)
- Check if this rule is already synced (look for the marker comment `<!-- shared-rule: <rule-name> -->`)
  - If already exists: replace the old version with the new content
  - If not exists: append to the end of CLAUDE.md
- Wrap the synced content with markers for future updates:

```markdown

<!-- shared-rule: <rule-name> -->
[content from shared-rules/<rule-name>.md]
<!-- /shared-rule: <rule-name> -->
```

- Show the user what was synced and where

## Important
- Always use marker comments to track which rules are synced
- When replacing, replace everything between the opening and closing markers (inclusive)
- Never modify any content outside the markers
- If no CLAUDE.md exists in the project, ask the user where to create it
