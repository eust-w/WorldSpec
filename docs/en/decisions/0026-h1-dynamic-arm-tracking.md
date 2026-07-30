---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0026-h1-dynamic-arm-tracking.md
last-verified: 2026-07-30
---

# ADR-0026: H1 Fixed-Base Four-Joint Dynamic Arm Tracking

The Chinese document is the normative source; this page is its official
translation.

## Context

A5-CF Job `worldspec-h1-midterm-45v9r` executed normally on a Drobodata A800
with Profile Digest `sha256:2fd53b...02a54`. The handoff repair behaved as
intended: the task phase no longer violated `right_hip_yaw`, and there were no
NaNs, capacity overflows, or abnormal contacts.

The control gate still failed on `fall_height`. The Trace shows that:

- all 25 `whole_body_settle` steps used the Stand Policy;
- the first 62 `track_handle` steps still used Stand while the QP continuously
  changed the torso and right arm;
- the base accelerated backward, and Motion was entered only after the QP
  command norm reached `0.05`;
- minimum base height reached `0.777434 m`, triggering `fall_height`;
- no joint limit was violated and Task Handoff itself did not fail.

Raising the Motion entry threshold or relaxing the height gate therefore does
not address the failure. The evidence now isolates the problem to manipulation
motion shifting the center of mass beyond what the frozen Stand Policy can
stabilize.

## Decision

Adopt the minimal A5-CG variant:

1. Preserve the scene, three policies, seed, quality gates, joint ranges,
   termination rules, and explicit `qfrc_bias` feed-forward.
2. Lock planar base velocity, base yaw, and torso velocity to zero in the QP.
   Control only `right_shoulder_pitch`, `right_shoulder_roll`,
   `right_shoulder_yaw`, and `right_elbow`.
3. Hold the torso and uncontrolled upper-body joints at the Profile reference
   targets instead of replacing the reference with the current drifted pose.
4. Keep the Stand Policy active during the task phase. Add no hidden
   constraint, mocap pull, kinematic teleport, or relaxed gate.
5. Bind the new Profile to the A5-CF Report, Controller, and Trace Digests.
6. Pass the fixed-base MuJoCo CPU tracking gate before building a new image and
   running exactly one single-GPU A800 control Spike.

## Executed result

A5-CG Job `worldspec-h1-midterm-9zmdg` completed on a real A800 with Profile
Digest `sha256:994c9a...3cb0d`. Dynamic-arm isolation and the Stand Policy were
active as designed, with no joint-limit violation, NaN, or handoff failure, but
the 301st Trace record triggered `fall_height`. The control gate therefore
failed and the Controller remained `non_publishable`.

The new Trace further shows that the TCP was briefly stable near
`[1.8351, -0.1891, 1.1411] m`, while the old handle target remained
`[1.87, -0.21, 1.075] m`. Continuing toward the low target drove the QP into a
near-singular elbow configuration, after which the upright base slid
backward. A5-CG therefore proves that locking base command and torso alone
does not compensate for unsuitable task geometry.

## Release boundary

- A pass creates only an internal `control_candidate`.
- It does not prove physical grasp, the full drawer task, 5/5, L3, or 100M
  training.
- The A5-CF failure evidence remains immutable.
- Another A5-CG failure requires a new Trace-based decision about
  balance-aware manipulation rather than silent parameter tuning.
