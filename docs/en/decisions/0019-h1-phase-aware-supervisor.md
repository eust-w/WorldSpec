---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0019-h1-phase-aware-supervisor.md
last-verified: 2026-07-29
---

# ADR-0019: H1 phase-aware three-policy supervisor

The Chinese document is the normative source; this page is its official translation.

## Context

The A800 calibration in ADR-0018 produced a Capture Policy that passed its
gate. Across five real traces, a stable window with linear speed at most
`0.12 m/s` and angular speed at most `0.20 rad/s` appeared between control
steps 174 and 181 after the zero command, followed by a static final
0.2-second hold.

This does not prove that the static Stand Policy can take over. A2 already
showed that a fixed-time direct blend from motion to stand fails. The next
step must therefore separately test:

```text
Motion Policy → Capture Policy → Stand Policy
```

## Decision

Add an evaluation-only `phase_aware_supervisor_probe` research stage with no
PPO updates:

- use only the frozen transition-v2 Motion Policy while a motion command is
  active;
- enter the frozen A3 Capture Policy when the command becomes zero;
- run Capture for at least 20 and at most 40 control steps;
- allow handoff only after linear speed is at most `0.12 m/s` and angular
  speed is at most `0.20 rad/s` for five consecutive steps;
- linearly blend Capture and the passing `stand-v2.1` policy for five control
  steps;
- use only Stand after the blend, with at least ten pure Stand control steps
  before the episode ends;
- mark `supervisor_candidate` only when all five walk/settle and all five
  Stand regression tests pass with clean runtime diagnostics;
- fail closed if Capture reaches its limit, Stand is never activated, Stand
  dwell is too short, or any historical quality gate fails;
- digest-bind the controller, all three checkpoints, trace, target bundle,
  OCI image, package lock, and source commit, while keeping artifacts
  `research_only / internal_only`.

## Boundary

This probe proves only three-policy switching for the fixed target model and
fixed four-second evaluation. It:

- neither starts nor authorizes the 100M formal run;
- does not prove the walk–open drawer–grasp mug–place–close drawer task;
- does not prove robustness over randomized initial states;
- is not kitchen L3, a publicly releasable policy, or real-robot safety
  evidence.

Only a passing real A800 A4 report may permit a later decision about using the
supervisor in a longer-horizon task.
