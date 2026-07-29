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
