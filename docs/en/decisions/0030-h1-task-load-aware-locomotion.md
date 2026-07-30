---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0030-h1-task-load-aware-locomotion.md
last-verified: 2026-07-30
---

# ADR-0030: H1 Task-Load-Aware Locomotion

The Chinese document is the normative source; this page is its official
translation.

## Context

A5-CK proved that constraining the base-recovery command to the Motion Policy's
training domain is still insufficient to stabilize H1. With the right arm
holding its task pose and bias-force feed-forward, the frozen policy continued
to slide backward under a `+0.5 m/s` command and terminated on `fall_height`.
Changing PD gains or relaxing the height gate would not determine whether the
lower-body policy learned whole-body balance under this load.

## Decision

Add a `loaded_track_settle_task_load` research calibration stage:

1. Warm-start from the frozen transition-v2 Checkpoint, restoring the
   normalizer, policy, and value networks while resetting the optimizer.
2. On the final H1 plus right-hand Robotiq dynamics, apply the nine-dimensional
   A5-CK held-joint pose and bias-force feed-forward as a read-only task load,
   sampled at a `0.5–1.0` scale for each Episode.
3. Sample initial base longitudinal velocity in `[-0.1, 0.1] m/s` to cover
   small backward-slip disturbances.
4. Do not extend the observation ABI or change command distribution,
   transition curriculum, rewards, termination conditions, or any of the ten
   quality gates. This stage tests whether the policy can adapt implicitly
   through dynamics feedback.
5. Run one A800 calibration with 16,777,216 steps, 4,096 environments, and
   eight evaluations. Always hand off and digest-verify the Checkpoint, Report,
   Trace, and environment lock.
6. Only `formalTrainingGate=passed` may feed this Checkpoint into one bounded
   whole-body control Spike. On failure, stop and use the evidence to decide
   whether explicit load observations or a redesigned control interface are
   required.

## Boundaries

- Passing task-load calibration creates only an internal research policy; it
  is not automatically a public policy or kitchen L3.
- This stage does not start full A5, 5/5, or 100M training.
- The fixed arm pose and feed-forward replay A5-CK evidence; they do not cover
  every manipulation posture or load distribution.
- If implicit adaptation without load observations fails, the next design must
  separately review an observation-ABI change rather than silently breaking
  Checkpoint compatibility.
