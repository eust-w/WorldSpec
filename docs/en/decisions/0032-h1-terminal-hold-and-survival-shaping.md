---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0032-h1-terminal-hold-and-survival-shaping.md
last-verified: 2026-07-30
---

# ADR-0032: H1 Terminal-Hold Measurement and Survival Shaping

The Chinese document is the normative source; this page is its official
translation.

## Context

`loaded_track_settle_task_load_retention` executed 16,777,216 real steps on a
Drobodata A800 and evaluated all seven Checkpoints. The formal gate still
failed:

- selected mean Episode length was `500.7891 < 900`, degrading to `387.9922`
  at the end;
- training termination was dominated by `fall_height`;
- all five loaded-stand regressions passed;
- all five walk-settle tests passed except `maximumSettleLinearSpeed`;
- the historical evaluator treated the entire one-second deceleration phase as
  the static-hold window, so the expected velocity of about `0.35 m/s`
  immediately after the zero-command transition also failed the gate;
- recalculating the same Trace over the final `0.2 s` yielded linear speed
  `0.048–0.078 m/s` and angular speed `0.083–0.113 rad/s`, below the unchanged
  limits.

ADR-0018, the Capture Profile, and the Supervisor Profile already define settle
measurement as the final `0.2 s` static hold after a one-second deceleration
phase. The retention stage omitted that field and therefore assigned different
semantics to the same behavior. PPO reward was also clipped nonnegative before
termination and had no termination penalty, so it could not directly learn to
avoid `fall_height`.

## Decision

Add a `loaded_track_settle_task_load_survival` research stage:

1. Preserve the one-second deceleration phase and the existing `0.20 m/s` and
   `0.40 rad/s` limits, but define the authoritative measurement window as its
   final `0.2 s`. This does not relax a threshold.
2. Warm-start again from the original retention-v3 Checkpoint, not from the
   degraded task-load-retention Checkpoint. The latter remains failure-lineage
   evidence only.
3. Preserve the full A5-CK task load, Stand/Capture dual teachers, observation
   ABI, termination conditions, curriculum proportions, and every formal
   quality gate.
4. Add `terminationPenalty=25` so terminations such as `fall_height` affect the
   learnable return. Add Stand/Capture teacher-action error costs of `1.0` each
   so positive rewards cannot hide policy drift.
5. Reduce learning rate to `2e-5` and entropy cost to `5e-4`; retain the other
   training dimensions.
6. Continue evaluating every Checkpoint and require mean Episode length of at
   least `900/1000`, five passing walk-settle tests, and five passing
   loaded-stand tests. Every failing candidate remains `non_publishable`.
7. Permit exactly one gated A800 calibration. A pass stops at the internal
   locomotion-candidate boundary and does not automatically run A5, 5-of-5,
   100M, or L3.

## Boundaries

- This decision corrects inconsistent evaluation semantics; it changes no
  speed, drift, attitude, or Episode threshold.
- Termination and teacher-action costs are research reward shaping and do not
  prove real-robot stability.
- If the Episode gate still fails, the next control or observation design
  requires a separate decision based on the termination distribution; there is
  no automatic tuning.
- A pass proves only a loaded-locomotion candidate under the locked model,
  Profile, Checkpoint, and deterministic tests.
