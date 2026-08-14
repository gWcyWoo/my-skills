# ICP implementation contract v1

`icp.implementation-contract.v1` is the immutable boundary between exact task and
design evidence and implementation workers. Compile it once in the main ICP
session before any test or production edit. An implementation worker may consume
it but may never create, edit, weaken, or replace it.

## Source projection

ICP deterministically projects every non-empty line of each exact v5 member
`source_contract` into `source_clauses` with a stable ID, exact JSON source path,
original text, source digest, page identity, source kind, and minimum evidence
kind. The complete ordered list is SHA-256 bound in the compiler input. Projection
never replaces the lossless source contract.

The compiler maps every source clause exactly once to an observable clause. It may
split one source clause into more precise acceptance cases, but may not drop it,
attach it to another page/owner, or reduce its evidence. Behavior, requirement,
and acceptance clauses require integration evidence; declared UT and E2E add their
own levels. Unit evidence never replaces integration. A design clause requires
both the frozen design artifact and visual evidence.

Source projection is syntactic; semantic classification happens in the main ICP
compiler. Use this public compatibility table:

| Source kind | Allowed observable `clause_type` |
| --- | --- |
| `interface` | `interface` |
| `design` | `visual` |
| `behavior` | `behavior` |
| `requirement` | `interface`, `behavior`, or `visual` according to its exact text |
| `acceptance` | `behavior` or `visual` according to its exact assertion |

All source kinds grouped into one observable clause must share the selected type.
For example, a UI requirement may compile as `visual`; it then requires both its
original integration minimum and `visual` evidence. Do not force UI prose into a
behavior clause merely because it appeared in a requirement section. A rejected
type reports the exact clause ID, source kinds, allowed types, and actual type.

No product capability is universal. Language switching, dismissal, navigation,
icons, validation copy, or any other behavior becomes a clause only when the exact
Sheet contract, exact design evidence, existing project contract, or explicit user
decision requires it.

Sheet and design sources are always present. When a behavior comes only from an
existing public project contract or an explicit user decision, add the optional
top-level `context_source_clauses` list before dispatch. It is not a free-form
feature wishlist: each item is a task-local `behavior` source, requires at least
integration evidence, and binds the exact text to a live provenance file under the
flow-state directory. Use `origin=project-contract` for a copied read-only project
contract excerpt and `origin=user-decision` for a verbatim decision recorded by
the main ICP session. The exact item shape is:

```json
{
  "clause_id": "stable task-local source ID",
  "page_id": "exact implemented page ID",
  "source_path": "/task-context/user-decision/1",
  "source_kind": "behavior",
  "exact_text": "exact behavior decision",
  "source_digest": "sha256 of exact_text UTF-8 bytes",
  "required_evidence": ["integration"],
  "origin": "user-decision",
  "provenance_path": "/absolute/flow-state/user-decision-1.txt",
  "provenance_sha256": "live provenance file sha256"
}
```

Every context source is covered exactly once by the same observable clause,
acceptance-case, and TDD rules as Sheet sources. The provenance SHA is rechecked
before every node dispatch and final evidence validation. Omit the entire optional
field when there are no task-local sources; an empty list is also accepted.

## Compile before edits

For every implementation DAG node, declare one public target and copy its exact
`allowed_paths`. For each page, fetch every exact design reference once into the
flow state and bind each raw/normalized reference or exported asset by absolute
path and live SHA-256. Analyze all required reachable states before dispatch:

- deterministic setup/action and state name;
- viewport, density, font scale, locale, theme, system bars, and animations;
- measured geometry anchors (`name`, `expected`, `tolerance`);
- named pixel regions and maximum mismatch ratio;
- typography, colors, and assets visible in that state;
- the precise reference artifact used by that state.

Reuse one fetched/normalized design bundle across state analysis. Do not fetch the
same reference independently in each worker. Do not infer missing product copy,
states, assets, or interactions. A real incomplete or contradictory contract uses
the controlled failure path before production editing.

Each observable clause declares its source clause IDs, page and owner node,
preconditions, public action/input, exact expected observables, forbidden effects,
required evidence kinds, and applicable design state IDs. Each executable evidence
obligation has an acceptance case. Every integration case belongs to exactly one
ordered TDD slice with an explicit valid-RED condition and minimum-GREEN scope.

`record-contract` validates the envelope, compiler-input/job digests, exact source
coverage, public interfaces, ownership equality, design artifacts/states,
observable clauses, acceptance cases, and TDD coverage. It writes the canonical
contract once and freezes its SHA-256. Only then may `next-node` emit a v2 worker.

Use this exact top-level shape. Copy identities, source digest, ownership, and node
IDs from the compiler input; compute `compiler_input_digest` with canonical JSON
(`ensure_ascii=false`, sorted keys, separators `,`/`:`). The main ICP session must
author the semantic fields shown as examples from the exact sources and design:

```json
{
  "kind": "icp.implementation-contract.v1",
  "schema_version": 1,
  "job_id": "exact compiler-input job_id",
  "job_digest": "exact compiler-input job_digest",
  "compiler_input_digest": "sha256 canonical compiler input",
  "source_clauses_digest": "exact compiler-input source_clauses_digest",
  "context_source_clauses": [],
  "public_interfaces": [{
    "interface_id": "stable interface ID",
    "owner_node_id": "exact DAG node ID",
    "public_target": "exact public component/route/function target",
    "inputs": [],
    "outputs": []
  }],
  "ownership": [{
    "node_id": "exact DAG node ID",
    "allowed_paths": ["exact/path/from/DAG"]
  }],
  "design_contracts": [{
    "design_id": "stable design ID",
    "page_id": "exact page ID",
    "reference_artifacts": [{
      "artifact_id": "stable artifact ID",
      "path": "/absolute/flow-state/reference.png",
      "sha256": "live artifact sha256"
    }],
    "states": [{
      "state_id": "stable state ID",
      "name": "runtime visual state name",
      "setup": "exact deterministic reachability action",
      "reference_artifact_id": "stable artifact ID",
      "viewport": {
        "width": 390,
        "height": 844,
        "density": 1.0,
        "font_scale": 1.0,
        "locale": "contract-required locale",
        "theme": "light",
        "system_bars": "included|excluded",
        "animations_disabled": true
      },
      "anchors": [{
        "name": "card_top",
        "node_id": "card",
        "attribute": "top",
        "expected": 100.0,
        "tolerance": 1.0
      }],
      "regions": [{
        "name": "card",
        "bbox": [16, 577, 358, 220],
        "max_mismatch_ratio": 0.05
      }],
      "typography": [{"name": "title", "properties": {"size": 24, "weight": 600}}],
      "colors": [{"name": "surface", "value": "#FFFFFFFF"}],
      "assets": [{
        "name": "leading icon",
        "artifact_id": "exported-icon-artifact",
        "content_sha256": "same live sha256 as that artifact"
      }]
    }]
  }],
  "observable_clauses": [{
    "clause_id": "stable observable ID",
    "page_id": "exact page ID",
    "owner_node_id": "exact owner node ID",
    "clause_type": "interface|behavior|visual",
    "source_clause_ids": ["exact source clause ID"],
    "preconditions": ["observable precondition"],
    "action": "public input/action",
    "expected_observables": ["exact visible/state/data outcome"],
    "forbidden_effects": [],
    "required_evidence": ["integration"],
    "design_state_ids": []
  }],
  "acceptance_cases": [{
    "case_id": "stable case ID",
    "clause_ids": ["stable observable ID"],
    "level": "unit|integration|e2e",
    "preconditions": ["exact setup"],
    "action": "exact public action",
    "expected_observables": ["exact assertion"]
  }],
  "tdd_slices": [{
    "slice_id": "stable ordered slice ID",
    "owner_node_id": "exact owner node ID",
    "clause_ids": ["stable observable ID"],
    "integration_case_ids": ["stable integration case ID"],
    "red_contract": "missing/wrong behavior that must fail first",
    "green_scope": "minimum behavior allowed for GREEN"
  }],
  "untested_boundaries": []
}
```

Empty typography/color/asset lists are valid only when the exact state truly has
none to extract; they are not a shortcut around design analysis. Every implemented
DAG node has exactly one public interface and ownership entry. Every implemented
page has exactly one design contract and at least one state. The union of visual
clause state IDs must equal all declared design state IDs.

## Evidence and terminal coverage

Each v2 worker result binds the frozen contract and writes
`icp.acceptance-evidence.v1`. Required `(clause ID, evidence kind)` pairs must equal
actual bindings exactly. Test evidence points to a live SHA-bound JUnit XML and a
passed named testcase for each acceptance case. Visual evidence maps frozen state
IDs to canonical visual states, uses the same frozen reference SHA/calibration,
and may not loosen anchor or region thresholds. Runtime evidence uses canonical
runtime provenance. Static contract/design evidence points to frozen artifacts.

The v5 finalizer reloads and revalidates every persisted worker result and artifact,
then derives the ordered required and covered clause ID lists itself. It emits
`icp.flow-handoff-result.v2` only when they are identical. Handoff prose or a
generic `passed` value cannot satisfy coverage.
