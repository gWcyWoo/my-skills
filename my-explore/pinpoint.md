# Pinpoint

The query names a specific symbol, file, UI label, or area plus element.

## Steps

1. **Locate the symbol.**
   - **Symbol name known** -> `mcp__language_server__get_project_symbols query="<name>"`
   - **File known, symbol unknown** -> `mcp__language_server__get_symbols file_path="<file>"`, then pick the symbol from the outline
   - **UI text or literal known** -> `mcp__ast_grep__find_code` on the JSX or template pattern, or `rg -n` on **non-source files only** such as i18n files, templates, or markdown

2. **Extract the body.** -> `mcp__probe__extract_code files=["<file>#<symbol>"]`. Batch related symbols into one call: `files=["a#x","b#y","c#z"]`.

3. **Follow delegations.** -> `mcp__language_server__get_symbol_definitions` at the call site, then return to step 2 at the new location.

**Never use `rg` on source files in this playbook.** If the instinct is to search a `.ts` file for a symbol name, use `mcp__language_server__get_project_symbols` instead.

**Stop condition:** every item in `<target>` has been reported. Typical cost: 1–2 tool calls.
