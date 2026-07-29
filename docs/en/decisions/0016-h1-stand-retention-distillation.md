---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0016-h1-stand-retention-distillation.md
last-verified: 2026-07-29
---

# ADR-0016: H1 stand replay and teacher-action distillation

The Chinese document is the normative source; this page is its official translation.

## Context

The ADR-0015 A800 transition calibration improved part of the post-walk braking
metrics, but zero-command stand regression degraded from 5/5 to 0/5. The prior
training distribution contained very little independent stand rehearsal and
exhibited clear stand-capability forgetting. The failed result cannot be fixed
by relaxing the original behavior gates.

## Decision

Select A1 and retain one unified policy while making stand retention an explicit
training distribution and read-only teacher constraint:

- warm-start normalizer, policy, and value from the failed ADR-0015 internal
  checkpoint, while resetting the optimizer;
- make each 200-control-step cycle 60% move for 150 steps then zero for 50
  steps, and 40% zero-command stand replay for the entire cycle;
- use the passing `stand-v2.1` checkpoint as a deterministic read-only teacher;
- apply the teacher only during stand replay, converting student/teacher action
  mean-squared error into a distillation reward;
- describe this method as teacher-action distillation, not strict policy KL;
- run a small calibration with 8,388,608 target steps, 4,096 environments, six
  evaluations, a `1e-4` learning rate, and `0.003` entropy coefficient;
- retain CCD=50, all ten original behavior gates, and
  `research_only / internal_only`;
- stop on failure without automatic tuning, retry, or a 100M run.

## Evidence boundary

Before a real run, the Profile, Schema, environment reward, teacher loading, and
A800 Job path are only an `Accepted Design` and implementation baseline. Only a
real A800 report can prove:

- successful teacher-checkpoint loading and network-ABI compatibility;
- actual stand replay and distillation execution in JAX/MJX training;
- whether all ten behavior gates pass.

Even a passing calibration creates only an internal locomotion candidate; it is
not evidence for the complete kitchen task or L3.

## Consequences

- the failed transition policy and passing stand policy remain separate student
  initialization and teacher evidence;
- the report binds both checkpoints by digest, size, and selected step;
- the report adds teacher-action-error diagnostics, while release remains
  controlled only by the unchanged physical behavior gates;
- a larger training run requires both this calibration result and a subsequent
  user decision.
