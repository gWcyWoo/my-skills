# Test rules — E2E

Loaded by the `test-writer` subagent only when the user requests E2E tests, together with `general.md`.

- E2E cases formalize ONLY the scenarios the user and the coordinator agreed on in natural language — never invent or add scenarios.
- Hazards nobody enumerated surface only when the real assembly runs (E2E, including the manual end-to-end check after green — gate 4 of `~/.claude/CLAUDE.md` `<tdd-flow>`); every hazard discovered there MUST be sedimented back into an automated case.
- The shared discipline in `general.md` applies unchanged: determinism, deadline polling instead of bare sleeps, contract-stating case names.
