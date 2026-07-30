---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0028-h1-task-origin-base-recovery.md
last-verified: 2026-07-30
---

# ADR-0028: H1 Task-Origin Base Recovery

The Chinese document is the normative source; this page is its official
translation.

## Context

A5-CH Job `worldspec-h1-midterm-ddkxh` ended with `fall_height` on a real
Drobodata A800. The calibrated handle was inside the observed stable
workspace, but the base slid continuously backward after right-arm tracking
started. The fixed world target caused the arm to keep extending, amplifying
the base displacement.

The existing Motion Policy has passed the short-walk stage, while Capture and
Stand Policies have their own evidence. The smallest next change is not a
hidden constraint or relaxed gate, but reuse of the existing leg policies to
restore the planar base position recorded at task start.

## Decision

Adopt one gated A5-CJ run:

1. Record the planar base origin on first entry into the task phase.
2. Generate a deterministic PD command from position error and local velocity,
   with separate forward, backward, and lateral limits; keep yaw command zero.
3. Enter Motion Policy when recovery-command norm reaches `0.05`; below `0.02`,
   reuse the existing Capture stability gate and five-step Blend to Stand.
4. Freeze the last stable right-arm target and bias feed-forward throughout
   base recovery. Resume the current task-space solution only after returning
   to Stand.
5. Preserve the A5-CH scene, three policies, seed, Controller, termination
   rules, and every quality gate. Add no mocap, weld, kinematic teleport, or
   hidden grasp constraint.
6. Bind the new Profile to the A5-CH Report, Controller, and Trace Digests, and
   record recovery commands, active steps, and arm-target source.
7. After local contract checks and fixed-base preflight pass, run exactly one
   single-GPU A800 Spike. A pass creates at most an internal
   `control_candidate`; a failure first archives its real termination evidence.

## Boundary

- Fixed-base CPU preflight proves only arm tracking, not base-recovery behavior.
- One A5-CJ run does not prove physical grasp, drawer actuation, cup placement,
  5/5, L3, or 100M training.
- A5-CH failure evidence remains immutable and A5-CJ cannot retroactively
  change its conclusion.

## Execution result

A5-CJ Job `worldspec-h1-midterm-dlrnk` executed on a real Drobodata A800.
The Report, Controller, and 368-row Trace were handed off and SHA-256 verified,
but `formalControlGate=failed` with `fall_height`; the Controller remains
`non_publishable`.

The Trace shows residual forward base velocity at task entry. PD velocity
damping immediately produced negative `vx`, while the frozen Motion Policy was
trained only on non-negative longitudinal commands. The policy then oscillated
under this out-of-domain command and arm disturbance and could not recover after
substantial backward velocity developed. This conclusion applies only to this
A5-CJ run and does not rewrite prior failure evidence.
