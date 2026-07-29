---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0015-h1-transition-braking-calibration.md
last-verified: 2026-07-29
---

# ADR-0015: H1 transition-braking curriculum and single-candidate CCD spike

The Chinese document is the normative source; this page is its official translation.

## Context

The real A800 `loaded-track-settle-v1` run passed walking, posture, stand
regression, and mean-episode-length gates, but all five tests failed the
original settling-speed gates. That result is failure evidence and must not be
rewritten as a pass by lowering thresholds. The log also contained two
recommendations to increase `ccd_iterations=35`. They were not CCD-capacity
overflows, but require an independent check before another training run.

## Decision

Select option A:

- retain the original `0.20 m/s` settling linear-speed and `0.40 rad/s`
  settling angular-speed gates, together with every other gate;
- add an explicit move-to-zero curriculum: 75% of cycles move for 150 control
  steps and then use a zero command for 50 control steps;
- add linear-velocity and yaw-velocity settling rewards only during that
  zero-command phase, while reducing the action-change penalty weight there;
- warm-start from the failed internal `loaded-track-settle-v1` checkpoint,
  restoring normalizer, policy, and value while resetting the optimizer;
- test exactly one predeclared CCD candidate before retraining: `35 → 50`;
- release the transition-calibration Job only when a 4,096-environment,
  200-step batched trace has no iteration advisory, CCD-capacity overflow, or
  other capacity overflow;
- stop on a failed spike or calibration, without automatic tuning or retry.

## Evidence boundary

This ADR and its Profile, Schema, Worker, and Job are an `Accepted Design` and
implementation baseline. The CCD=50 spike passed on a real A800 over 4,096
environments and 200 steps with zero iteration advisories and capacity
overflows. The subsequent transition calibration completed but failed its
gate. The evidence does not prove that:

- the transition curriculum improves settling;
- the midterm policy passes;
- formal 100M training is released.

Even a passing transition calibration only releases formal locomotion training;
it is not evidence for the complete kitchen task or L3.

## Executed result

The transition calibration reached 17,203,200 reported steps with a final mean
episode length of 903.4375. Post-walk maximum settling linear speed improved to
0.4020–0.4377 m/s and angular speed to 0.4131–0.4529 rad/s, but both remained
above the original gates. More importantly, all five zero-command stand
regressions failed with planar drift of 0.5112–0.5447 m. Option A therefore
does not release formal training, and no 100M Job was created.

See the complete normalized
[`locomotion-transition.a800.failed.json`](../../../examples/h1-kitchen/locomotion-transition.a800.failed.json)
report.

## Consequences

- the original failed report and checkpoint become immutable experiment inputs;
- CCD numerical evidence and reward/curriculum evidence remain separate;
- new artifacts remain `research_only / internal_only / non_publishable`;
- the unchanged ten-test behavior gate still controls formal training.
