# Pinpoint

The query names a specific symbol, file, UI label, or area + element.

## Steps

1. **Locate the symbol.**
   - **Symbol name known** → `LSP workspaceSymbol query="<name>"`
   - **File known, symbol unknown** → `LSP documentSymbol filePath="<file>"`, then pick the symbol from the outline
   - **UI text or literal known** → `ast-grep find_code` on the JSX or template pattern, or `Grep` on **non-source files only** (i18n files, templates, markdown)

2. **Extract the body.** — `probe extract_code files=["<file>#<symbol>"]`. Batch related symbols into one call: `files=["a#x","b#y","c#z"]`.

3. **Follow delegations.** — `LSP goToDefinition` at the call site, then return to step 2 at the new location.

**Never use `Grep` on source files in this playbook.** If the instinct is to `Grep` a `.ts` file for a symbol name, use `LSP workspaceSymbol` instead.

**Stop condition:** every item in `<target>` has been reported. Typical cost: 1–2 tool calls.
