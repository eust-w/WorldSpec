---
status: Accepted Design
applies-to: WorldSpec 0.1
normative-language: en
normative-source: ../../../docs/zh-CN/decisions/0046-h1-manipulation-hard-negative-replay.md
mirror: ../../zh-CN/decisions/0046-h1-manipulation-hard-negative-replay.md
last-verified: 2026-07-30
---

# ADR-0046: Replay the fixed hard manipulation state

## Status

Accepted Design. The Chinese document is the normative source.

## Context

The corrected v13 Job `worldspec-h1-midterm-vgtfz` completed 16,777,216 training
steps, seven Checkpoints, and 14/14 isolated suite evaluations on a real
Drobodata A800. Every candidate passed from-rest `5/5`, but every candidate
reached only post-walk `4/5`; Step 4,915,200 remained the selected candidate.

The failure always occurred in fixed `post_walk_capture` run 2. The trajectory
completed all 100 steps without early termination or non-finite values, but
violated translation, lateral drift, posture, height, and terminal velocity
gates. Recomputing the frozen JAX reset mapping identified index `565` in the
4,096-state bank.

v13 trained with 50% from-rest resets and 50% uniform bank resets. A single bank
index is therefore expected in only `4096 × 0.5 / 4096 = 0.5` environments per
reset. Seven candidates failing the same state indicates insufficient exposure
to a known hard state, rather than a reason to continue the same distribution
or relax the gates.

## Decision

Add `hard-negative-replay-frozen-bank-checkpoint-portfolio-v14`:

- warm-start from the v13 Step 4,915,200 Checkpoint, restoring the normalizer,
  policy, and value while resetting optimizer state;
- freeze the training reset mixture at 50% from-rest, 25% index `565`, and 25%
  uniform frozen-bank resets;
- preserve the bank Blob, dynamic right-arm trajectory, unbounded recovery
  costs, training steps, candidate count, seeds, action ranges, and all gates;
- bind the Profile to the v13 Report, Trace, Checkpoint, and hard-state
  derivation evidence;
- record `snapshotCurriculum` explicitly in the Report instead of relying only
  on the effective Profile Digest;
- force formal `post_walk_capture` evaluation to zero hard-state probability
  and 100% uniform-bank probability, preserving the original five fixed seeds
  and state mapping;
- continue to run formal `from_rest` evaluation without a state bank.

This changes the optimization distribution, not the quality gate. High-frequency
hard-state replay cannot change the formal test cases.

## Gates

- v14 must still pass post-walk `5/5`, from-rest `5/5`, and the frozen Episode
  length gate;
- any failure keeps the policy `non_publishable` and stops the route;
- a v14 pass unlocks only one full-kitchen run;
- that single run must pass before an independent kitchen `5/5`;
- this decision does not authorize 100M training, automatic retry, gate
  relaxation, or an L3 claim.
