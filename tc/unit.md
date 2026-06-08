# Test rules — unit

Loaded by the `test-writer` subagent in the unit plan phase, together with `general.md`.

## Unit tests own

- complex pure logic;
- large boundary matrices;
- branches integration cannot reliably reach (timeout timing, signals, fork-level mechanisms — mechanism tests are unit even when they cross a process);
- minimal reproductions of historical bugs.

## Constraints

- Unit cases may call unexported symbols but lock conclusions (input → output/effect), never code shape.
- Needing to mock a network or a process inside a unit test signals the case belongs to integration — defer it to the integration plan (report it under `Notes` as deferred-to-integration).
- Unit cases never duplicate what an interface-level case already locks, and never exist merely to pin private implementation details.
