---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
normative-source: ../../../docs/zh-CN/decisions/0047-h1-hard-negative-replay-result.md
mirror: ../../zh-CN/decisions/0047-h1-hard-negative-replay-result.md
last-verified: 2026-07-30
---

# ADR-0047: H1 hard-negative manipulation replay result

The Chinese document is the normative source; this page is its official
translation.

## Status

Accepted.

## Context

Job `worldspec-h1-midterm-2pn45` executed
`hard-negative-replay-frozen-bank-checkpoint-portfolio-v14` on a real
Drobodata A800. It used the locked image `sha256:7d445d05…2a73d`, completed
16,777,216 training steps, saved seven Checkpoints, and completed all 14
formal suite evaluations in isolated CUDA processes.

Training resets were exactly:

- 50% from rest;
- 25% fixed hard snapshot-bank index `565`;
- 25% uniform frozen-bank samples.

Formal evaluation retained the five v13 fixed seeds, original uniform-state
mapping, and unchanged quality gates.

## Result

The runtime chain completed and all four primary artifacts were handed off.
The Report, Checkpoint, Trace, and state bank passed local SHA-256
verification. Every candidate had the same classification:

```text
post_walk_capture: 4/5
from_rest:         5/5
overall:           9/10
```

The frozen selection rule chose step `7,372,800` on its mean Episode length
of `99.5/100`, but its formal manipulation-balance gate still failed. Fixed
post-walk test 2 completed all 100 steps without early termination or
non-finite values, yet reached:

```text
minimum base height:            0.7160
minimum upright cosine:         0.7536
maximum base translation:       0.8543 m
maximum lateral drift:          0.5396 m
maximum terminal linear speed:  2.8208 m/s
maximum terminal angular speed: 2.1256 rad/s
```

All six metrics improved over the selected v13 candidate, but the formal gate
did not change. This evidence proves only that replaying one state at 25%
frequency was insufficient under the current contract. It does not by itself
prove that the state is unrecoverable or identify viability, observation
aliasing, control authority, or reward design as the root cause.

## Decision

- keep the v14 policy `non_publishable`;
- do not start one full-kitchen run;
- do not start independent kitchen 5/5;
- do not start 100M training;
- do not relax any quality gate;
- do not automatically tune or retry;
- require a new control-design ADR that freezes a new experimental variable
  and falsifiable hypothesis.

Acceptable research directions include:

1. diagnose viability and recoverability to determine whether state `565`
   has a successful witness under the current action range and controller;
2. add an explicit recovery Supervisor or recovery phase instead of requiring
   one manipulation policy to absorb the dynamic state;
3. prove observation aliasing before changing the observation/state ABI.

This ADR deliberately does not select among those routes, so the failed gate
is not misrepresented as a root-cause conclusion.

## Evidence

- Report: `sha256:1757154e…381ac`
- Checkpoint: `sha256:b40d6287…b7fae`
- Trace: `sha256:2b29a5be…782b0`
- state bank: `sha256:d4090fe9…8cec0`
- redacted summary:
  `examples/h1-kitchen/locomotion-manipulation-hard-negative-replay.a800.quality-failed-summary.json`
