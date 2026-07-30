---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0029-h1-forward-only-base-recovery.md
last-verified: 2026-07-30
---

# ADR-0029: H1 Forward-Only Base Recovery

The Chinese document is the normative source; this page is its official
translation.

## Context

The real A5-CJ A800 Trace showed that task-phase PD velocity damping could
produce negative `vx`, while the frozen Motion Policy command distribution was
`vx ∈ [0, 0.6] m/s`. The recovery system therefore drove the policy outside its
training domain. Under arm disturbance, negative commands did not provide
stable braking and the run terminated with `fall_height`.

## Decision

Run one gated A5-CK attempt:

1. Preserve the A5-CJ scene, seed, three frozen policies, Controller, arm-freeze
   behavior, termination conditions, and every quality gate.
2. Restrict longitudinal recovery commands to `[0, 0.5] m/s`; clamp negative
   position-error or velocity-damping results to zero instead of sending
   out-of-domain backward commands to the Motion Policy.
3. Preserve lateral commands in `[-0.1, 0.1] m/s` and keep yaw at zero.
4. Bind the A5-CK Profile to the A5-CJ Report, Controller, and Trace digests.
5. After Schema, contract, and fixed-base CPU preflight gates pass, run exactly
   one A800 Spike. On failure, archive all evidence without automatic retry,
   tuning, or subsequent training.

## Boundaries

- Fixed-base preflight does not validate dynamic base braking.
- A5-CK can produce at most an internal `control_candidate`.
- It does not automatically launch full A5, 5/5, 100M training, or L3
  certification.
- If A5-CK still cannot brake under in-domain commands, the next step is to
  evaluate a task-load-aware lower-body policy or retraining rather than relax
  quality gates.
