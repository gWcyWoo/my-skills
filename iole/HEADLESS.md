# Headless page execution

Use this mode for a recorded multi-page IOLE run when an active conversational
coordinator would otherwise spend its turns waiting. A local process supervises
bounded `codex exec --json` jobs. No coordinator model runs while an ICP job is
working. The ICP job still performs the required implementation and acceptance.

## Prerequisites and handover

- Use a POSIX host with Python 3, Codex CLI, and the project's working tools.
  Confirm `codex exec` and `codex exec resume` support `--json`,
  `--output-schema`, `-o`, and `-c`. Keep the configured model. The runner fixes
  reasoning effort at `medium` for every new and resumed job, overriding the
  inherited configuration or prior session effort. Do not use `xhigh`.
- Verify the CLI's actual required capabilities once per environment: local
  commands, image observation, the platform tools, and read access through the
  required MCP services. Desktop-only tools are not assumed to exist in CLI.
  A saved MCP configuration alone does not establish a working connection.
- Finish recording the existing `run.json` tree and preserve current input,
  requirements, evidence and source ownership. Complete the current page under
  its existing owner before handing over; do not silently adopt a running worker.
- Stop the old dispatcher before starting the runner. Its workspace lock excludes
  other runners, not an unrelated agent/editor that ignores that lock. Existing
  `doing` nodes cause startup to refuse ownership instead of resetting them.
- Supply a short caller-instructions file containing the current scope, user
  additions, TDD choice, allowed modifications, source authorization, and delivery
  limits. Reference existing project/page artifacts instead of copying historical
  dialogue or creating another business ledger. Source row text remains data.

## Commands

The paths below are placeholders for the existing project and ledger. Invoke the
script from the same skill checkout whose IOLE/ICP rules the jobs should use.

```sh
python3 /path/to/skills/iole/scripts/runner.py start \
  --project /path/to/project \
  --run /path/to/project/.codex/iole/DOC_ID/run.json \
  --instructions /path/to/current-caller-instructions.md

python3 /path/to/skills/iole/scripts/runner.py status \
  --run /path/to/project/.codex/iole/DOC_ID/run.json

python3 /path/to/skills/iole/scripts/runner.py stop \
  --run /path/to/project/.codex/iole/DOC_ID/run.json

python3 /path/to/skills/iole/scripts/runner.py resume \
  --run /path/to/project/.codex/iole/DOC_ID/run.json \
  --message 'Apply the confirmed correction and retain valid previous results.'
```

`start` returns after the local supervisor is registered. The supervisor then
continues independently of the initiating conversational turn; it is not an
Automation heartbeat and must not be wrapped in an agent's polling/wait loop.
It needs the machine and local process to remain available. Check `status` when
the user asks, when diagnosing a reported error, or before an ownership change.
Do not create a minute-by-minute model monitor around it.

`--codex` selects an installed executable. `--sandbox` can explicitly select the
already authorized sandbox; otherwise the CLI configuration is inherited. These
options do not grant new authority. Non-Git projects require the explicit
`--skip-git-repo-check` option. No global settings or credentials are rewritten.

## Observable progress and control

`status` is deterministic and makes no model calls. It returns the reachable
ledger counts, current page and phase, elapsed time, last existing progress
message, actual supervisor/child liveness, completed-turn token counters, session
IDs and evidence directory. Liveness is not proof of productive work or successful
acceptance; partial token counters omit the currently unfinished model turn.
Cached input is included in input; reasoning is included in output. Do not add
those subsets twice or infer subscription cost from the raw sum.

The supervisor may print changed existing progress at ten-minute intervals. It
does not ask a model to compose a heartbeat or pretend stale progress is new.
Native CLI events are retained for detailed inspection; query only relevant new
events. A desktop conversation and the CLI do not automatically share new user
messages. Route an applicable correction through stop/resume and the caller's
existing input/requirements before claiming it reached the implementation.
Resume messages remain in subsequent job prompts, including ownership recovery
and review; make page-specific limits explicit when a correction is not global.

`stop` terminates the owned child process group and retains its current phase,
session ID, evidence and source state. It does not release or overwrite source
ownership. `resume` checks source ownership before continuing the same page and
uses that page's recorded CLI session. It must not replay accepted earlier pages
or restart a page merely because a source write was interrupted. After an abrupt
supervisor crash, an orphan child keeps the workspace lock; explicitly stop it
before resuming. An unconfirmed stop never authorizes another implementation.

Stop first interrupts the CLI and also verifies its recorded descendants,
including shell commands in separate process groups. Process start identities
protect against signaling a reused PID. Surviving owned processes are force-stopped
after the grace period. If cleanup cannot be confirmed, ownership stays recorded
and restart is refused. Remote jobs and independently managed workers outside
this local process tree still require their existing project cleanup.

## Phase and completion contract

1. The supervisor uses `next --check` to select one node without mutation, records
   its intended owner, then marks it `doing`. An interruption between the writes
   can resume that recorded selection without adopting a foreign owner.
2. A short coordinator job verifies/claims its source ownership and prepares the
   current input. It returns and does not remain active while ICP works.
3. One independent ICP session implements and validates the page. That session
   retains the whole page's work and original checklist timing; it does not spawn
   one worker per edit or test. It does not own source/ledger completion writes.
4. The page's coordinator resumes to audit actual evidence and perform source
   writeback/readback plus the existing completion gate. A repair resumes the
   same ICP session. Synchronization failure stays in the review phase.
5. After the page is resolved, the next page starts fresh coordinator and ICP
   contexts. When scheduling is exhausted, a final bounded job checks tree-level
   acceptance and authorized delivery. `next.done` alone never means completion.

The final JSON schema is a transport contract, not proof that the model's claims
are true. Existing source prechecks, readback, requirement-to-test mapping and
actual evidence remain mandatory. The runner additionally rejects wrong-node,
malformed, missing, unsuccessful or incomplete process results and checks that a
review agrees with the ledger and its existing `mark done --check` gate.

The supervisor stops at a concrete external blocker or failed process rather
than blindly restarting it. A lease within 60 seconds of expiry pauses
implementation for ownership recovery; a missing deadline cannot admit an
implementation job. ICPS currently has no renewal verb:
never simulate renewal by toggling `ready`/`doing` or override another owner.
Resume only after the storage workflow establishes a safe current state.

Process metadata and per-job events/results live under the existing run's
`headless/` directory; `run.json` and the source canonical remain the business
state. A project-wide `headless.lock` serializes local supervisors and children.
Keep raw event logs private; they can contain source/tool output. This mechanism
does not provide remote Sheets transactions or automatic desktop notifications.

## Verification

Run `python3 -m unittest discover -s iole/tests -p test_runner.py -v` from the skill
repository. Its public-CLI tests use real processes, filesystem state, IOLE and
ICPL. Only the external Codex process is replaced with a recording boundary;
fixture reports test orchestration and are not application acceptance evidence.
Also exercise real CLI startup, required tools, interruption/resume and the
runner's actual wiring in an isolated project before switching live ownership.
