# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

SSOT of machine contracts for the product-governance path
`Idea → RankedBacklog → ProductProposal → human gates → approved`, plus the
deterministic tool that enforces them (package `impresario`). The LLM authors
artifact *content*; the validator owns *admissibility* of objects and state
transitions; authority decisions are made by a human and recorded as immutable
GateDecisions. This repo is self-contained: consumers vendor pinned copies of
contracts, never live references. Docs and READMEs are in Russian; code and
docstrings are in English.

## Commands

```bash
uv sync
uv run pytest                          # full suite
uv run pytest tests/test_loop.py -k name   # single test
uv run ruff format . && uv run ruff check .
uv run pyrefly check

uv run impresario validate contracts/examples/pp-001   # bundle (dir): schema + cross-checks
uv run impresario validate path/to/artifact.yaml       # schema-only (files); --bundle forces cross-checks
uv run impresario hash <idea.yaml>                     # canonical input_hash
uv run impresario backlog rank <ws> --backlog-id BL-x [--apply --actor <id> --expected-version N]
uv run impresario backlog select <ws> IDEA-xxx --expected-version N --actor <id> --reason "..."
uv run impresario forconcept init|run|resume <ws> ...
uv run impresario gate readiness|decide <ws> ...
```

Validator output is a JSON report on stdout; exit codes are stable API:
0 = clean, 1 = violations, 2 = usage error. The contracts dir is found by
walking up from cwd (`--contracts DIR` overrides).

## Architecture

Contracts live in `contracts/<name>/v1/` (JSON Schema 2020-12, `$id` =
`urn:impresario:contract:<name>:v1`) with `fixtures/` next to each schema.
Coverage invariants: every contract has ≥1 valid and ≥1 invalid fixture; the
canonical bundle `contracts/examples/pp-001` validates clean; every cross-check
has a test that breaks it. Editing a schema without a version bump is allowed
only if it does not narrow the set of valid documents. Domain semantics
(ProductProposal FSM, gates, scoring, researcher ↔ creator loop, `needs_human`)
are specified in `docs/semantics.md` — change semantics there and in code
together. Contract kind is detected from ID fields/prefixes (`IDEA-`, `ASMT-`,
`PP-`, ...); internal refs are URIs like `proposal://PP-001` and must resolve
within a bundle (fail-closed).

`src/impresario/` pipeline: `loader.py` (parse + kind detection) →
`schemas.py` (schema validation) → `checks.py` (cross-artifact checks with
stable codes: `REF_*`, `FSM_*`, `GATE_ORDER`, `LOOPSTATE_*`, ...) →
`report.py` (findings, exit codes). On top of that:

- `engine.py` — deterministic rank engine (P-07): same normalized assessments
  + policy ⇒ same backlog; a new LLM call is a new evaluation run, never a
  silent re-rank.
- `commands.py` + `workspace.py` — Stage 4 rank/select over a workspace
  (`ideas/`, `assessments/`, `backlog.yaml`, `runs/`, `decisions/`). All
  writes go through CAS (`input_hash` per assessment, `--expected-version`,
  monotonic version), a single-writer lock, and validate-then-atomic-replace;
  outputs must pass the same contracts they were written against.
- `loop.py` + `agents.py` — forconcept reference runner (semantics oracle for
  future execution backends). Durable artifacts on disk are the *only* state:
  stage completion is derived from files, so crash/resume at any boundary is
  idempotent. Fail-closed: an invalid artifact is never persisted (verdict
  `failed`, exit 1); verdicts are terminal (re-run is a no-op). `ScriptedAgent`
  replays pre-authored artifacts and doubles as the golden-fixture format.
- `gate.py` — typed QG-5: readiness is a *computed* precondition (never
  persisted); decisions are immutable, corrected only via `supersedes`; legal
  transitions come from the FSM table, not the decision name.
- `hashing.py` — canonical hash of the *parsed* document (YAML comments don't
  change it; semantic edits do).

Preserve these invariants in any change: determinism, fail-closed validation,
CAS + lock on every read-check-write, immutability of decisions/run records,
time comparisons via RFC 3339 parsing (never lexicographic).

## Working notes

- `pilot/` is a live workspace with real history (immutable `runs/`,
  `decisions/`, `forconcept/pp-101/`). Treat it as evidence, not scratch data —
  don't regenerate or hand-edit its records.
- `TODO.md` is the work queue (milestone status, handoffs to sibling repos).
- This repo is part of a polyrepo (see parent `CLAUDE.md`): changes only via
  PR, human merges; never edit sibling repos from here.
- Scope boundary: this repo is not an orchestrator and not engineering SDLC —
  no task execution, DAGs, or deployment.
