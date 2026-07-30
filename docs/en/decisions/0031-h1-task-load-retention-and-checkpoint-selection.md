---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0031-h1-task-load-retention-and-checkpoint-selection.md
last-verified: 2026-07-30
---

# ADR-0031: H1 Task-Load Retention and Checkpoint Selection

The Chinese document is the normative source; this page is its official
translation.

## Context

`loaded_track_settle_task_load` executed 16,777,216 real steps on a Drobodata
A800. Training had no NaN, capacity overflow, or abnormal contact, but the
formal gate failed:

- terminal mean Episode length was `774.3047 < 900`;
- all five walk-settle runs ended with `0.48–0.56 m/s` linear speed, above the
  `0.20 m/s` limit;
- all five loaded-stand runs drifted `0.287–0.315 m`, above the `0.20 m` limit;
- mean Episode length degraded from `922.2813` early in training to `774.3047`
  at the end.

Implicit dynamics feedback alone therefore damaged stand retention, and
packaging only the terminal Checkpoint can discard evidence that an
intermediate policy was stronger.

## Decision

Add a `loaded_track_settle_task_load_retention` research stage:

1. Warm-start from the completed retention-v3 Checkpoint, restoring normalizer,
   policy, and value while resetting the optimizer.
2. Use stand-v2.1 as the `stand_replay_only` teacher and the A3-passing Capture
   Policy as the `transition_settle_only` teacher.
3. Use 75% walk-settle and 25% stand replay. Apply the full A5-CK right-arm held
   pose and bias-force feed-forward, with neither partial-load sampling nor
   extra initial velocity.
4. Reduce learning rate to `5e-5` and entropy cost to `0.001`; strengthen the
   settle reward while preserving every formal gate and termination condition.
5. Evaluate every saved PPO Checkpoint with the same five walk-settle and five
   stand-regression tests. Rank by formal gate, passed-test count, Episode gate,
   normalized violation, Episode length, and then the earlier step.
6. Package only the selected Checkpoint and record every candidate's step,
   gate results, and normalized violation in the Report. Selection cannot turn
   a failing candidate into a pass.
7. Run one real A800 calibration. On failure, hand off all evidence and continue
   design without automatically starting A5, 5-of-5, 100M, or L3.

## Boundaries

- This stage does not change the observation ABI. Explicit load observations
  require a separate ADR if dual teachers under full load still fail.
- The Capture teacher constrains only the settle window and does not replace the
  task-phase Supervisor.
- Intermediate Checkpoint selection preserves degradation evidence; it is not
  early stopping or a relaxed gate.
- Passing this stage creates only an internal locomotion candidate and does not
  prove the full kitchen task.
