---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0023-h1-a5c-control-spike-failure.md
last-verified: 2026-07-30
---

# ADR-0023: evidence boundary after the H1 A5-C A800 control-Spike failure

The Chinese document is the normative source; this page is its official
translation.

## Confirmed facts

On 2026-07-30, A5-C executed on one NVIDIA A800-SXM4-80GB in Drobodata. Job
`worldspec-h1-midterm-d5z6c` completed normally with a `Succeeded` Pod. The
runtime image was `sha256:684daf...9f94c` and the input Profile digest was
`sha256:84175b...787fd`. Both controller and trace artifacts were copied back
and passed SHA-256 verification.

The result was `formalControlGate=failed` and
`controllerStatus=non_publishable`:

- H1 completed the frozen 150-step walk and 50-step
  Motion-to-Capture-to-Stand handoff;
- whole-body control entered `whole_body_settle` and terminated with
  `done=true` after 19 steps;
- TCP error fell from `0.167584 m` to a minimum of `0.010992 m`, and was
  `0.026351 m` at termination, so the QP brought the end effector inside the
  position tolerance;
- TCP speed was still `0.253163 m/s` at termination and never formed the
  required 20-step stable hold;
- base translation was `0.033109 m`, lateral drift was `0.010167 m`, minimum
  height was `0.988330 m`, and minimum upright cosine was `0.991174`;
- maximum QP projected gradient was `4.08e-8`, with no NaN, capacity overflow,
  CCD overflow, or abnormal-contact log.

The executed trace recorded only `done=true`, not the environment
`joint_limit`, `fall_height`, `fall_upright`, and `nonfinite` termination
subchannels. Therefore `logDiagnostics.clean=true` proves only that the
log-scanned channels were empty; it cannot prove that no joint-limit
termination occurred. The exact termination reason must remain `unknown`.
See
[`whole-body-control.a800.failed-summary.json`](../../../examples/h1-kitchen/whole-body-control.a800.failed-summary.json).

## Boundary

- a passing fixed-base CPU preflight is not a passing A800 whole-body control;
- temporarily entering the position tolerance is not a stable-control pass;
- handle grasping, drawer manipulation, kitchen 5/5, and 100M training were
  not executed;
- the failed controller cannot be labelled a candidate, integration asset, or
  L3;
- no threshold change, tuning, or new A800 job may be launched before the next
  route is selected.

## Decision required

### A5-CI (recommended): add termination diagnostics and replay once unchanged

- keep controller matrices, weights, gates, and input policies unchanged;
- add the four termination subchannels, joint positions and velocities, torque
  saturation, and active policy to the trace;
- build a new image and replay exactly one control Spike;
- if it fails again, use the exact termination reason for a new controller
  design and do not automatically retry.

This is the smallest information-gain step and avoids treating an unknown
termination as a gain-tuning problem.

### A5-CR: redesign the whole-body controller contract now

Redesign velocity bounds, target horizon, damping, joint-limit protection, and
base/arm priority. This changes the controller Profile, cannot be compared as
an unchanged replay, and requires a new CPU gate.

### A5-S: stop the H1 kitchen route

Keep the CPU-pass and A800-fail evidence and spend no further A800 resources
until a mature whole-body manipulation policy, real mount calibration, or
external controller is available.
