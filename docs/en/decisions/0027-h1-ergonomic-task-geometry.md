---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0027-h1-ergonomic-task-geometry.md
last-verified: 2026-07-30
---

# ADR-0027: H1 Ergonomic Task-Geometry Calibration

The Chinese document is the normative source; this page is its official
translation.

## Context

A5-CG Job `worldspec-h1-midterm-9zmdg` executed 301 Trace records on a real
Drobodata A800 and failed on `fall_height`. Diagnostic channels were complete,
with no joint-limit violation, non-finite value, policy-handoff failure, or
capacity anomaly.

The Trace shows that the TCP reached a low-speed stable state near
`[1.8351, -0.1891, 1.1411] m`, while the old self-authored drawer handle was at
`[1.87, -0.21, 1.075] m`. Continuing another 6.6 cm downward drove the
four-joint right-arm QP toward a near-singular elbow configuration; the base
then slid backward and fell.

## Decision

Adopt the minimal A5-CH correction:

1. Preserve all three policies, seed, Controller, termination rules, and
   quality gates without relaxing thresholds.
2. Preserve A5-CG fixed base command, fixed torso, four-joint right-arm QP, and
   explicit `qfrc_bias` feed-forward.
3. Translate the self-authored drawer, cup, and support together by
   `[-0.03, 0, +0.065] m`, producing
   `primitive-drawer-cup-v3-ergonomic`.
4. Move the handle target with physical geometry to
   `[1.84, -0.21, 1.14] m`; changing only a Predicate or controller target
   without changing collision geometry is forbidden.
5. Bind the new Profile to the A5-CG Report, Controller, and Trace Digests and
   retain the change as Derivation evidence for generated task geometry.
6. After fixed-base CPU preflight passes, run exactly one single-GPU A800
   Spike. Failure remains `non_publishable`; a pass creates at most an internal
   `control_candidate`.

## Boundary

- This calibrates a self-authored generated scene to the robot workspace; it
  does not alter a measured real-kitchen observation.
- It does not prove physical grasp, drawer actuation, cup placement, 5/5, L3,
  or 100M training.
- A5-CG failure evidence remains immutable and A5-CH cannot retroactively
  change its conclusion.
