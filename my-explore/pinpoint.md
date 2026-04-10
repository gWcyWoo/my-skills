# Pinpoint

The query names a specific symbol, file, UI label, or area plus element.

## Stages

Work in this order and do not skip a stage:
- **Existence** — does the target object exist at all?
- **Shape** — what declaration, export, or enclosing-node shape does it use?
- **Body** — where is the body to extract?
- **Delegation** — does the resolved body immediately hand off elsewhere?

## Steps

1. **State the target object and current stage.**
   - Example: "Target object = `app/api/foo/route.ts` handler related to `POST`; current stage = Existence."
   - Do not ask caller/callee questions while Existence or Shape is unresolved.

2. **Resolve Existence and Shape file-locally first.**
   - **Symbol name known, file unknown** -> `mcp__language_server__get_project_symbols query="<name>"`
   - **File known, symbol unknown, and LSP available** -> `mcp__language_server__get_symbols file_path="<file>"`, then pick the symbol from the outline
   - **File known and declaration shape unresolved** -> stay inside the known file or nearest directory:
     - first scoped anchor on exact text known -> `rg -n` on the known file or nearest relevant directory
     - code shape known -> `mcp__ast_grep__find_code` scoped to the known file's nearest relevant directory
   - **UI text or literal known** -> `mcp__ast_grep__find_code` on the JSX or template pattern, or `rg -n` on non-source files such as i18n files, templates, or markdown
   - Do not widen to project-wide search while a known file still has unresolved Existence or Shape, unless the file path itself is now in doubt.

3. **Reset the hypothesis when evidence disagrees.**
   - Two failed attempts to prove the same declaration or export-shape hypothesis means the hypothesis is weak.
   - Do not keep varying tools on that same hypothesis.
   - Rewrite the hypothesis instead: indirect export, wrapper, alias, or absence. Then continue from the appropriate stage.

4. **Extract the body only after Existence and Shape are confirmed.** -> `mcp__probe__extract_code files=["<file>#<symbol>"]`. Batch related symbols into one call: `files=["a#x","b#y","c#z"]`.

5. **Follow delegations.** -> `mcp__language_server__get_symbol_definitions` at the call site, then return to step 4 at the new location.

**Use `rg -n` on source files only as a first scoped anchor when the exact file is already known and the exact text being tested is known.** Do not use it as a broad source browser.

**Stop condition:** every item in `<target>` has been reported. Typical cost: 1–3 tool calls.
