# Pinpoint

The query names a specific symbol, file, UI label, or area + element.

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
   - **Symbol name known, file unknown** → `LSP workspaceSymbol query="<name>"`
   - **File known, symbol unknown** → `LSP documentSymbol filePath="<file>"`, then pick the symbol from the outline
   - **File known, code shape unresolved** → `ast-grep find_code` scoped to the known file or nearest directory
   - **UI text or literal known** → `ast-grep find_code` on the JSX or template pattern, or `Grep` on **non-source files only** (i18n, templates, markdown)
   - Do not widen to project-wide search while a known file still has unresolved Existence or Shape.

3. **Reset the hypothesis when evidence disagrees.**
   - Two failed attempts to prove the same declaration or export-shape hypothesis means the hypothesis is weak.
   - Do not keep varying tools on that same hypothesis.
   - Rewrite the hypothesis instead: indirect export, wrapper, alias, or absence. Then continue from the appropriate stage.

4. **Extract the body only after Existence and Shape are confirmed.** — `probe extract_code files=["<file>#<symbol>"]`. Batch related symbols into one call: `files=["a#x","b#y","c#z"]`.

5. **Follow delegations.** — `LSP goToDefinition` at the call site, then return to step 4 at the new location.

**Never use `Grep` on source files.** Use `LSP`, `ast-grep`, or `probe` instead.

**Stop condition:** every item in `<target>` has been reported. Typical cost: 1–3 tool calls.
