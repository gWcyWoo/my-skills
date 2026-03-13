---
name: gemini
description: Execute tasks using Google Gemini CLI. Use for Gemini model analysis, code generation, or when user requests Gemini specifically. Supports gemini-3-pro-preview only.
---

# Gemini API Skill

## Quick Start
```bash
# 1. Write prompt to temp file
cat << 'EOF' > /tmp/gemini_task.txt
Your task here
EOF

# 2. Execute
gemini -p "$(cat /tmp/gemini_task.txt)" -m "gemini-3-pro-preview" --output-format text -s
```

**Key flags:**
- `-p, --prompt`: Task prompt
- `-m, --model`: Gemini model (default: gemini-3-pro-preview)
- `--output-format text`: Plain text output
- `-s, --sandbox`: Sandbox mode
- `-i, --prompt-interactive`: Interactive mode

## Common Patterns

### Pattern 1: Code Generation (Direct File Modification)

For code generation tasks, Gemini generates and writes code directly. No Claude Code intervention needed.
```bash
# Step 1: Create prompt with full context
cat << 'EOF' > /tmp/gemini_code.txt
[Current code context if needed]

Task: [Specific code generation task]

CONSTRAINTS:
- Generate complete, production-ready code
- Include all necessary imports and dependencies
- Return ONLY the code, no markdown, no explanation
- Ensure code is executable as-is
EOF

# Step 2: Execute and write directly to file
gemini -p "$(cat /tmp/gemini_code.txt)" -m "gemini-3-pro-preview" --output-format text -s > output_file.py
```

### Pattern 2: Code Modification (In-Place Updates)

For modifying existing code, Gemini reads, modifies, and writes back:
```bash
# Step 1: Create modification prompt
cat << 'EOF' > /tmp/gemini_modify.txt
Modify the following code to [specific change]:

$(cat existing_file.py)

CONSTRAINTS:
- Return ONLY the complete modified code
- No markdown formatting, no explanations
- Ensure all original functionality is preserved
EOF

# Step 2: Execute and overwrite
gemini -p "$(cat /tmp/gemini_modify.txt)" -m "gemini-3-pro-preview" --output-format text -s > existing_file.py
```

### Pattern 3: Analysis Tasks (Detailed Output)

For analysis, provide comprehensive results:
```bash
cat << 'EOF' > /tmp/gemini_analysis.txt
Analyze the following code/content and provide:
1. Key findings
2. Potential issues
3. Optimization opportunities
4. Detailed recommendations

[Content to analyze]
EOF

gemini -p "$(cat /tmp/gemini_analysis.txt)" -m "gemini-3-pro-preview" --output-format text -s
```

### Pattern 4: File Processing
```bash
# Create prompt
cat << 'EOF' > /tmp/gemini_process.txt
Process this content: [instructions]
EOF

# Execute with pipe
cat input.txt | gemini -p "$(cat /tmp/gemini_process.txt)" -m "gemini-3-pro-preview" --output-format text -s > output.txt
```

## Available Models

- `gemini-3-pro-preview` (recommended for all tasks)
- `gemini-2.5-flash` (codebase analysis only)

## Output Formats

- `text`: Plain text (use for all outputs)

## Workflow Guidelines

### Code Generation Workflow
```bash
# 1. Prepare complete prompt with context
cat << 'EOF' > /tmp/gen_code.txt
Create a Python class for [functionality]
Requirements: [list requirements]
Return ONLY code, no explanation.
EOF

# 2. Generate and write directly
gemini -p "$(cat /tmp/gen_code.txt)" -m "gemini-3-pro-preview" --output-format text -s > new_module.py

# 3. Report summary to user
echo "✓ Generated new_module.py with [brief description]"
```

### Analysis Workflow
```bash
# 1. Prepare analysis prompt
cat << 'EOF' > /tmp/analyze.txt
Perform detailed analysis of:
[content/code to analyze]

Provide comprehensive findings with examples.
EOF

# 2. Execute and display full results
gemini -p "$(cat /tmp/analyze.txt)" -m "gemini-3-pro-preview" --output-format text -s
```

## Response Handling

### For Code Generation Tasks
**Report to user:**
- Brief summary of what was generated/modified
- File path(s) affected
- Key changes made (high-level only)

**Do NOT:**
- Show generated code in chat
- Explain code line-by-line
- Ask Claude Code to review or modify

### For Analysis Tasks
**Report to user:**
- Full analysis output from Gemini
- All findings, recommendations, and details
- Complete response without summarization

## Quick Reference

| Task Type | Command Pattern | Output Handling |
|-----------|----------------|-----------------|
| Code generation | `gemini -p "<task> Return ONLY code." -m "gemini-3-pro-preview" --output-format text -s > file.py` | Brief summary only |
| Code modification | `gemini -p "Modify: $(cat file.py) Return ONLY code." -m "gemini-3-pro-preview" --output-format text -s > file.py` | Brief summary only |
| Analysis | `gemini -p "Analyze: [content]" -m "gemini-3-pro-preview" --output-format text -s` | Full detailed output |
| File processing | `cat input \| gemini -p "<task>" -m "gemini-3-pro-preview" --output-format text -s > output` | Context-dependent |

## Troubleshooting

**Rate Limits:**
```bash
gemini -p "task 1" -m "gemini-3-pro-preview" -s
sleep 2
gemini -p "task 2" -m "gemini-3-pro-preview" -s
```

**Clean Output:**
- Add "Return ONLY the result. No markdown. No explanation." to prompts
- Always use `--output-format text`
- Always use `-s` flag

## Best Practices

1. **Token Efficiency:**
   - Use temp files for prompts (avoid escaping issues)
   - Write generated code directly to files
   - Summarize code generation results (don't echo code back)

2. **Code Generation:**
   - Let Gemini handle all code creation/modification
   - Report only high-level summaries to user
   - No Claude Code intervention for generated code

3. **Analysis:**
   - Always show full detailed output
   - Include all findings and recommendations
   - Don't truncate or summarize analysis results

4. **Error Handling:**
   - Check exit status: `$?`
   - Validate output before overwriting files
   - Use `-s` for better error messages

## Integration Notes

- **Gemini handles**: Code generation, modification, specialized analysis
- **Claude Code handles**: Workflow orchestration, user communication, file management
- **Handoff**: Gemini → files → summary to user (for code tasks)
- **Handoff**: Gemini → full output to user (for analysis tasks)
