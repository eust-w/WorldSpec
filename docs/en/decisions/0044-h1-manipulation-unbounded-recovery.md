---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0044-h1-manipulation-unbounded-recovery.md
last-verified: 2026-07-30
---

# ADR-0044: Continue manipulation-balance calibration with unbounded recovery costs

## Status

Accepted Design.

The Chinese document is the normative source; this page is its official
translation.

## Context

`suite-isolated-v11` completed seven-candidate training and fourteen isolated
evaluations on a real Drobodata A800. Every candidate passed the from-rest
suite `5/5`, but the best post-walk result was only `4/5`. The frozen selection
rule chose the Step 4,915,200 candidate, whose second post-walk trajectory
terminated on `fall_height` at step 99/100.

The failing trajectory stayed stable for roughly forty steps, then accumulated
base-position and velocity error until the recovery command reached its
existing control limits. The current `baseAnchor` and `settleLinear` terms are
exponential rewards. Their gradients approach zero once errors become large,
so they no longer distinguish a bad recovery state from a worse one.

Oversampling only the fixed failing state would leak the formal evaluation seed
into training. This decision therefore neither oversamples that state nor
relaxes a gate.

## Decision

Add `unbounded-recovery-checkpoint-portfolio-v12`:

- warm start from the v11-selected Step 4,915,200 Checkpoint;
- restore normalizer, policy, and value while resetting optimizer state;
- preserve state-bank generation, the 50/50 reset distribution, training
  steps, candidate count, control ranges, evaluation seeds, and every quality
  gate;
- retain the existing exponential rewards;
- add a squared planar base-anchor error cost with weight `25.0`;
- add a squared planar settling-velocity error cost with weight `2.0`;
- keep independent `post_walk_capture` and `from_rest` evaluation processes for
  all seven candidates and use only the frozen selection rule for release.

These costs retain non-zero gradients at large errors. They change the recovery
training signal, not the task definition or acceptance threshold.

## Result semantics

- This ADR selects a research calibration route; it does not claim a passing
  policy.
- v12 must pass the complete formal manipulation-balance gate before one full
  kitchen run is unlocked.
- The full single run must pass before an independent kitchen `5/5` can start.
- This stage starts neither another 100M run nor a Controller Candidate or L3
  claim.
- A v12 failure must retain the real A800 report and Checkpoint and produce a
  new evidence-based ADR; it must not relax gates or retry automatically.

## Rejected alternatives

- Relaxing `fall_height`, drift, velocity, or pass-count gates.
- Oversampling only the Capture state associated with the fixed failing seed.
- Changing recovery command limits or task geometry while attributing the
  result to the same policy.
- Skipping the manipulation-balance gate and starting the full kitchen run or
  `5/5`.

## First-launch evidence

The first v12 Job, `worldspec-h1-midterm-pnwr5`, failed closed during
`input_verification`. All four input files completed chunked upload and Digest
verification, but the entrypoint had not registered the new
`loaded-track-settle-manipulation-suite-isolated-v11-failed` source stage and
reported `unsupported warm-start source stage`. GPU training never started, so
the strategy result is `not_evaluated`.

The correction only adds frozen-v11-summary field checks and Checkpoint path
selection. It changes no v12 Profile, training environment, reward, seed,
control range, or quality gate. Because this was a pre-training configuration
defect, one relaunch under a new Probe Revision is allowed after regression
tests pass.
