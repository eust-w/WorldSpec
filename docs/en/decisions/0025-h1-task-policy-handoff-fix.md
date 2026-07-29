---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0025-h1-task-policy-handoff-fix.md
last-verified: 2026-07-30
---

# ADR-0025: H1 task-phase leg-policy safe handoff

The Chinese document is the normative source; this page is its official
translation.

## Context

A5-CI Attempt-05 passed its formal diagnostic gate, but its control gate failed
on the `right_hip_yaw` joint limit. The 225-record Trace shows an abrupt event,
not slow drift. During `whole_body_settle`, the QP base-command norm crossed
below `0.01`, switching leg control from Motion Policy directly to Stand Policy
within one control period. `right_hip_yaw` control changed from about `+4 Nm` to
`-20 Nm`; velocity then reached about `+10/-15 rad/s` and crossed the unchanged
`[-0.43, 0.43] rad` range after several oscillations.

Four A800 diagnostic replays terminated at the same joint after the same
phase/policy transition. Historical A5-C and A5-CI evidence remains immutable;
this ADR decides only the new A5-CF control variant.

## Decision

1. Preserve the A5-C QP, scene, three policies, seed, MJX capacity, joint
   ranges, termination conditions, and quality gates. Do not pass by relaxing
   thresholds, changing ranges, or adding a hidden constraint.
2. Add an independent task-phase leg-policy Supervisor:
   - initialize in Stand;
   - enter Motion from Stand only at command norm `0.05`;
   - leave Motion for Capture only at command norm `0.02`;
   - reuse the A4 consecutive velocity-stability gate for Capture, capped at
     40 steps;
   - reuse the five-step linear action blend from Capture to Stand;
   - allow Motion re-entry from Capture/Blend when command reaches `0.05`.
3. The hysteresis interval prevents small QP base corrections from chattering
   around one threshold. Capture, Blend, and Stand observe a zero locomotion
   command while the original QP request remains in the Trace.
4. The new Profile binds the A5-CI Attempt-05 Profile, Report, Trace, and summary
   digests. A missing handoff contract or diagnostic lineage fails closed.
5. Gate one single-GPU A5-CF Spike behind Schema, state-machine, historical
   A5-C regression, and local CPU/MJX preflight. On failure, transfer Report,
   Controller, and Trace, then stop without automatic tuning.

## Release boundary

- An A5-CF pass yields only a `control_candidate`; it does not prove the full
  drawer task, 5/5, or L3.
- This stage does not start 100M PPO.
- Historical A5-C/A5-CI replay does not implicitly enable the new Supervisor.
- A new A800 failure requires a new evidence-based decision before expanding
  the repair.
