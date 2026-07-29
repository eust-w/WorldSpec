---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0021-h1-a5-failure-response.md
last-verified: 2026-07-29
---

# ADR-0021: response to the first H1 A5 behavior failure

The Chinese document is the normative source; this page is its official translation.

## Confirmed facts

On 2026-07-29, A5 completed its first real task run on one NVIDIA
A800-SXM4-80GB. The run used the pinned Motion, Capture, and Stand checkpoints
and image `sha256:f3eaaa71...89f0d8`. It ended with
`formalTaskGate=failed`; the remaining four runs were not executed and 100M
was not started.

The evidence shows:

- H1 moved forward 1.3973 m, with a minimum base height of 0.9883 m and a
  minimum upright cosine of 0.9941; there was no early termination, NaN, joint
  limit violation, or abnormal contact;
- the task stopped in `reach_handle`, where target error remained about
  0.3926 m after 100 steps;
- the mug fell from an initial height of 1.1928 m to the floor at about
  0.0349 m before the robot arrived, proving that the two side rails did not
  form a valid support surface;
- MJX logged 1,069 broadphase capacity overflows and requested at least
  `nconmax/naconmax=19`, while the one-environment capacity was 16.

The normalized failure report is
[`kitchen-task.a800.failed.json`](../../../examples/h1-kitchen/kitchen-task.a800.failed.json).
The full internal trace digest is `sha256:20d065ef...fc506f`.

## User decision required

### A5-R (recommended): repair the benchmark before judging control

- raise A5-specific contact capacity to at least 32;
- replace the ineffective side rails with a real collision support surface,
  without adding a weld, mocap, or hidden attachment;
- add a fixed-base IK reachability scan before A800 launch and constrain the
  cabinet placement to an explicit reachability margin;
- keep the frozen A4 policies, four-joint right-arm controller, and physical
  grasp boundary unchanged;
- rerun one gate and proceed to 5/5 only if it passes.

This route removes proven-invalid benchmark conditions first, so the next run
can distinguish controller limitations from an unexecutable scene.

### A5-C: upgrade manipulation control at the same time

Apply A5-R and additionally permit post-settle base micro-positioning or
task-space MPC/QP so the base and right arm jointly satisfy handle and mug
reachability. This is closer to real whole-body manipulation, but expands the
A5 control boundary and its validation surface.

### A5-S: retain the failure and stop

Use no further A800 resources. A5 remains `non_publishable` until real kitchen
geometry, validated mount evidence, or a stronger manipulation policy becomes
available.

Merely increasing the timeout or starting task training is not recommended:
the mug support and contact capacity are already known to be invalid, so that
would train against benchmark defects.
