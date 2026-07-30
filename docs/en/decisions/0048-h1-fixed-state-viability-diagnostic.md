---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
normative-source: ../../../docs/zh-CN/decisions/0048-h1-fixed-state-viability-diagnostic.md
mirror: ../../zh-CN/decisions/0048-h1-fixed-state-viability-diagnostic.md
last-verified: 2026-07-31
---

# ADR-0048: H1 fixed hard-state viability diagnostic

The Chinese document is the normative source; this page is its official
translation.

## Status

Accepted Design. No real A800 result exists yet.

## Context

The v14 training recorded by ADR-0047 still failed the formal
manipulation-balance gate on fixed post-walk hard-state index `565`. A failed
training run does not prove that the state is unrecoverable under the frozen
controller, observation ABI, and action range. Further reward changes or
retraining would not distinguish an infeasible state from a policy that failed
to find a recovery action.

The user selected route A: first search for a constructive action witness that
passes the original quality gates.

## Decision

Add the `loaded_track_settle_manipulation_viability` diagnostic:

- bind exactly to the v14 Step `7,372,800` Checkpoint, state bank, index `565`,
  evaluation Seed `2`, target model, and package lock;
- first replay the frozen policy with zero residual and reproduce every archived
  metric within `0.001` absolute tolerance;
- search bounded residuals over the frozen policy under the same 10-dimensional
  leg-action ABI and `[-1, 1]` action range;
- use 10 temporal knots, a 100-step horizon, 4,096 candidates, 128 elites, and
  12 CEM iterations, with residuals bounded to `[-0.5, 0.5]`;
- preserve all quality gates, model, initial state, random seed, controller,
  observations, and action dimensions;
- execute one single-GPU A800 diagnostic without training or automatic retry.

Result semantics are fixed:

```text
a trajectory passes the original gates
→ constructive_witness
→ proves only recoverability under the frozen contract

the search finds no trajectory
→ unknown
→ is not an infeasibility proof
```

`formalViabilityDiagnosticGate` covers lineage, baseline reproduction, search
completion, and diagnostic completeness. `formalWitnessGate` independently
records whether a constructive witness was found. The Controller remains
`non_publishable` in every outcome, and the diagnostic cannot unlock one full
kitchen run, 5/5, or 100M.

## Consequences

- A witness can provide action and state evidence for a future explicit
  recovery Supervisor, but it is not a publishable policy.
- A search miss requires a separate decision on a broader feasibility solver,
  observation aliasing, or a recovery Supervisor.
- Runtime or implementation defects may be corrected and rerun under new
  evidence. A normally completed search miss may not automatically expand its
  budget or retry.

## Evidence status

This ADR currently binds only the Profile, schemas, implementation, and local
tests. A real A800 Report, Witness, Search Progress, and Trace must be archived
after execution.
