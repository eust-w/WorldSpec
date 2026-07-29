---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0022-h1-a5r-dynamic-control-failure.md
last-verified: 2026-07-30
---

# ADR-0022: boundary choice after the H1 A5-R dynamic-control failure

The Chinese document is the normative source; this page is its official
translation.

## Confirmed facts

On 2026-07-30, A5-R completed one real gate on an NVIDIA A800-SXM4-80GB. The
Profile commit was `8a17027`, the runtime image was `sha256:da616c...def3`, and
the image source commit was `f8e0bdc`. The result was
`formalTaskGate=failed`; the remaining four runs were not executed and 100M
was not started.

A5-R removed all three benchmark defects seen in the first A5 run:

- all 10 IK targets passed from the actual settled state, with a maximum
  residual of `0.013819 m` and a minimum joint-limit margin of
  `0.307619 rad`;
- the mug remained on its support for the complete trace, with a minimum
  height of `1.193794 m` and a final height of `1.193856 m`;
- `capacityOverflowCount=0`, so broadphase and CCD capacity no longer
  overflowed.

H1 still walked 1.4032 m, with a minimum base height of 0.9883 m and a minimum
upright cosine of 0.9937. There was no early termination, NaN, joint-limit
violation, or abnormal contact.

The remaining failure is dynamic manipulation control:

- after the 25-step `stand_ready` phase, actual TCP target error was still
  `0.121290 m`;
- over 100 `reach_handle` steps, actual error went from `0.174114 m` to a
  minimum of `0.096223 m`, then increased to `0.146487 m`;
- TCP height fell from `1.043681 m` to `0.946329 m`, while the handle target
  height was `1.075 m`;
- both the preflight and per-step virtual IK solutions show that the target is
  kinematically reachable, but the four-joint PD/impedance execution does not
  track the solved joint target. Increasing the timeout cannot fix this.

The normalized report is
[`kitchen-task.a5r.a800.failed.json`](../../../examples/h1-kitchen/kitchen-task.a5r.a800.failed.json).
The complete internal trace digest is `sha256:f9680841...e907a`.

## Decision required

### A5-CG (recommended): add model gravity compensation and a dynamic tracking gate

- continue to control only the existing four right-arm joints, without base
  repositioning or hidden grasp constraints;
- use MuJoCo inverse dynamics or normalized bias forces for right-arm gravity
  compensation;
- add torque, error, and joint-velocity channels to the trace;
- make `stand_ready` require actual pose-error and velocity gates instead of
  elapsed time only;
- run a fixed-base CPU and A800 MJX joint/TCP tracking spike before rerunning
  A5.

This directly addresses the proven tracking gap while keeping the control
expansion minimal and separate from leg or whole-body control.

### A5-C: upgrade to whole-body task-space MPC/QP

Allow the settled base, torso, and right arm to adjust together, using
task-space MPC/QP or whole-body control. This is closer to the final
whole-body task, but materially expands control, collision, safety, and
validation scope.

### A5-S: stop here

Keep A5-R as `non_publishable` research evidence and spend no further A800
resources until a validated manipulation controller, real mount transform, or
external task policy becomes available.

Until the user decides, automatic gain tuning, retrying, proceeding to 5/5,
and task training are forbidden.
