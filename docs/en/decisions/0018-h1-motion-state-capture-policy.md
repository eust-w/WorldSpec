---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0018-h1-motion-state-capture-policy.md
last-verified: 2026-07-29
---

# ADR-0018: H1 motion-state capture policy

The Chinese document is the normative source; this page is its official translation.

## Context

The real A800 result for ADR-0017 proved that a static stand policy cannot take
over a moving gait state through a five-step action interpolation. The failure
is in the state distribution and gait phase, not in checkpoint ABI, model
binding, or runtime capacity.

The previous evaluation also called the entire one second after a zero command
the settling window and measured its maximum speed from the first control
step. That definition includes the pre-braking motion state and cannot
distinguish “stop within one second” from “remain still after stopping.” A2 was
still above threshold at its final step, so its historical failure is
unaffected by this contract issue.

## Decision

Add an independent `loaded_track_settle_capture` research stage:

- freeze the ADR-0017 motion policy as a read-only motion teacher;
- roll that policy in the final H1 plus right Robotiq model to generate 4,096
  real handoff states;
- sample handoff steps from 140–159 and commands from `vx 0.4–0.6 m/s`,
  `vy -0.05–0.05 m/s`, and `yaw -0.1–0.1 rad/s`;
- restore normalizer, policy, and value from the passing `stand-v2.1`
  checkpoint while resetting the optimizer;
- start each training episode from a handoff state, provide only a zero
  velocity command, and train for 100 control steps;
- use 8,388,608 PPO steps and 4,096 environments without domain
  randomization;
- keep the snapshot bank, checkpoint, and trace
  `research_only / internal_only`;
- return all evidence on failure, with no automatic tuning and no 100M job.

## Evaluation semantic correction

Keep the three-second walk, one-second zero-command interval, and original
thresholds, but separate their timing semantics:

- `settleWindowSeconds=1.0` is the total braking interval available to capture;
- `settleMeasurementWindowSeconds=0.2` is the final static-hold measurement
  interval;
- maximum linear speed during the measurement interval must be at most
  `0.20 m/s`;
- maximum angular speed during the measurement interval must be at most
  `0.40 rad/s`.

This does not relax either speed threshold. It prevents the braking initial
state from being mislabeled as an already settled state. A1 and A2 reports
remain unchanged and are not reinterpreted.

## Gate boundary

A formal Capture Candidate requires all of the following:

- all five motion-to-capture tests pass;
- all five capture-from-rest stand regressions pass;
- final mean training episode length is at least 90/100;
- no NaN, joint-limit violation, CCD/capacity overflow, or abnormal contact;
- the snapshot bank, both source checkpoints, target bundle, OCI image,
  package lock, and source commit are all digest-bound.

Even a pass proves only a motion-to-zero capture-policy candidate. A
phase-aware motion-to-capture-to-stand supervisor still requires a separate
probe; this is not kitchen L3 evidence and does not automatically trigger the
100M formal run.

## Real execution record

The first A800 Job, `worldspec-h1-midterm-n7ck6`, failed while generating
snapshots before PPO. An implementation error applied a 4,096-environment
selection mask through `tree_map` to MJX State capacity arrays with 65,536
rows, causing a broadcast-shape failure. This result is fixed as
`implementation_failure_before_training` and contains no policy-quality
evidence. The repair selects only per-environment `qpos`, `qvel`, and
`last_action`; it changes neither training hyperparameters nor quality gates.

The corrected Job, `worldspec-h1-midterm-rmnnr`, completed on one
NVIDIA A800-SXM4-80GB. It generated and verified 4,096 real motion handoff
snapshots, reached a final mean episode length of 100/100 after 8,601,600
reported steps, and passed all five motion-to-capture and all five
capture-from-rest tests. The five walking tests covered
1.3686–1.3729 metres with moving-phase velocity RMSE of
0.1516–0.1519 m/s. During the final 0.2-second measurement interval, maximum
linear speed was 0.0535–0.0637 m/s and maximum angular speed was
0.0623–0.0736 rad/s. The run had no NaN, joint-limit violation, CCD/capacity
overflow, or abnormal contact.

See the normative
[`locomotion-capture.a800.passed.json`](../../../examples/h1-kitchen/locomotion-capture.a800.passed.json)
report. The checkpoint, snapshot bank, and trace are bound to
`sha256:7f8c45e7…5cfbe`, `sha256:11a93ac2…9870`, and
`sha256:7ad8ca4d…4734`, respectively, and remain
`research_only / internal_only`. This result marks only a
`capture_candidate`; it started no formal 100M run and is not kitchen L3
evidence.
