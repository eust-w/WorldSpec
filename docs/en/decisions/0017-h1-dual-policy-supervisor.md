---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0017-h1-dual-policy-supervisor.md
last-verified: 2026-07-29
---

# ADR-0017: H1 motion/stand dual-policy supervisor

The Chinese document is the normative source; this page is its official translation.

## Context

The ADR-0015 transition policy improved part of braking but lost independent
stand capability. ADR-0016 A1 restored 5/5 stand regression through stand
replay and teacher-action distillation, but post-walk settling degraded again.
The two real A800 results show material capability interference when one policy
must cover motion, braking, and static balance under the present budget and
network architecture.

## Decision

Select A2, keep motion and zero-velocity/stand as two immutable policies, and
add an explicit supervisor:

- use the failed ADR-0015 transition checkpoint during motion because it is the
  best observed braking candidate, not because that policy passed;
- use the passing `stand-v2.1` checkpoint for zero velocity and stand;
- use the motion policy for the first 150 control steps of a walk test;
- after the zero command at step 150, linearly blend motion-policy action into
  stand-policy action over five control steps (0.1 seconds), with both policies
  observing a zero command during the blend;
- use only the stand policy from step 155 onward;
- use only the stand policy from step zero in stand regression;
- make this a zero-training, single-candidate probe that does not modify either
  checkpoint and does not automatically tune or retry;
- retain CCD=50 and the original ten behavior gates;
- keep reports, controller Manifest, and Trace
  `research_only / internal_only`;
- even a passing probe creates only an internal composite-controller
  candidate; it does not automatically start 100M training or prove kitchen L3.

## Evidence boundary

Before a real A800 run, the Profile, Schema, supervisor, and Job path are an
implementation baseline. Only a real report bound to both checkpoint digests,
the target bundle, OCI digest, package lock, and source commit can prove:

- both network ABIs match the final H1 plus right Robotiq environment;
- the declared action blend executed in MJX;
- whether all five walk-settle and five stand-regression tests pass;
- absence of NaNs, joint-limit violations, capacity overflow, and abnormal
  contact.

A failure must retain its report and Trace and stop downstream training.

## Consequences

- the H1 runtime changes from one policy to a policy set plus deterministic
  supervisor;
- the Controller Artifact binds both checkpoint digests and selected steps;
- the Trace records `activePolicy`, `blendAlpha`, and `actionJumpNorm`;
- A1 remains unchanged as evidence of unified-policy capability interference;
- if A2 fails, the next step requires a new evidence-based decision rather
  than a silent gate relaxation.

## Execution result

On 2026-07-29, A2 completed on one NVIDIA A800-SXM4-80GB. Both checkpoints
passed digest, size, selected-step, and 42-observation/10-action ABI checks. The
supervisor executed 150 motion steps, five action-blend steps, and stand-policy
takeover as specified. There was no early termination, NaN, joint-limit
violation, capacity overflow, or abnormal contact.

All five independent stand regressions passed. Maximum planar drift was only
0.021689–0.021690 m and maximum settling-window linear speed was
0.000303–0.000304 m/s. All five motion segments also passed displacement,
lateral drift, tracking, base-height, and upright gates.

All five walk-settle tests nevertheless failed. Maximum settling-window linear
speed was 0.4462–0.4549 m/s and maximum angular speed was
0.6169–0.7265 rad/s. At step 199, linear speed remained
0.2370–0.3146 m/s. The first blend step produced an action jump of
approximately 1.94–1.99, showing that action interpolation alone cannot make a
stand policy trained from rest smoothly capture a moving gait phase.

The `formalProbeGate` is therefore `failed` and the controller is
`non_publishable`. No 100M run, automatic tuning, or retry was started. See the
normalized
[`locomotion-dual-policy.a800.failed.json`](../../../examples/h1-kitchen/locomotion-dual-policy.a800.failed.json)
report.
