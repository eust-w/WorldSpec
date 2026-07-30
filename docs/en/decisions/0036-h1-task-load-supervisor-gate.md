---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0036-h1-task-load-supervisor-gate.md
last-verified: 2026-07-30
---

# ADR-0036: H1 task-load three-policy Supervisor gate

The Chinese document is the normative source; this page is its official translation.

## Context

The formal 100M run in ADR-0035 proved that the task-load motion policy can
pass five walk-settle tests. The same single policy drifted
`0.314–0.324 m` in zero-command stand regression and cannot be an independent
Policy Candidate. The Motion → Capture → Stand Supervisor from ADR-0019
previously passed ten deterministic tests without the task load.

Those separate results do not prove that the composition is valid. A complete
A5 run and kitchen 5/5 would also add arm control, contacts, and the task state
machine, making a failure hard to attribute. A task-load-only intermediate gate
is therefore required.

## Decision

Add the research-only `task_load_phase_aware_supervisor_probe` stage (A6-S):

1. use the terminal 100M Checkpoint only as the Motion Policy;
2. keep the Capture and Stand policies, consecutive velocity-stability gate,
   40-step Capture cap, five-step Blend, and minimum ten-step Stand Dwell;
3. inject the frozen A5-CK right-arm pose and feed-forward load at reset, with
   load scale fixed at `1.0` and no random base disturbance;
4. run no PPO and change no quality gate;
5. execute one deterministic probe on one Drobodata A800, with five
   walk-settle and five stand-regression tests;
6. permit a new single-run full-A5 Profile only when
   `formalTaskLoadSupervisorGate=passed`; permit fixed-kitchen 5/5 only after
   that A5 run passes;
7. on failure, transfer the Controller, Trace, and Report, then stop without
   automatic tuning, retry, A5 launch, or L3 claim.

A6-S has an independent Profile, Report Schema, result marker, and Controller
filename. Historical A4 Profiles and Reports remain unchanged.

## Evidence boundary

- The 100M policy remains `non_publishable / internal_only`.
- An A6-S pass creates only a `task_load_supervisor_candidate`, not a complete
  Controller Candidate.
- Code and Schema completion under this ADR do not prove that the A800 probe passed.
- Single-run A5 and kitchen 5/5 each require new runtime evidence.

## Subsequent gates

```text
A6-S task-load supervisor 10/10
  → one full A5 integration run
    → fixed-kitchen 5/5
      → L3 evidence review
```

Any failure stops at that stage with the exact evidence retained.
