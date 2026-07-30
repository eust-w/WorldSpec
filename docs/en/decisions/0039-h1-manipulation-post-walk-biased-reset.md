---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0039-h1-manipulation-post-walk-biased-reset.md
last-verified: 2026-07-30
---

# ADR-0039: H1 Manipulation Post-Walk-Biased Reset

The Chinese document is the normative source; this page is its official translation.

## Context

The mixed-reset-v3 Drobodata A800 job `worldspec-h1-midterm-hl78d` raised the
final mean Episode length from `88.0078125` to `94.359375` and improved the five
from-rest tests from `0/5` to `5/5`. The formal gate still failed because the
fifth post-walk initial state reached `0.3307465 m` maximum translation and
`0.9128384 m/s` terminal linear speed.

The training metric `eval/episode_state/from_rest_reset=50.0` proves that the
50/50 mixture was active. The audit also found that the nominal
`post_walk_capture` evaluation environment inherited the training mixture, so
two of its five seeds actually reset from rest. The suite therefore did not
cover five real post-walk snapshots and must be corrected rather than counting
rest-state passes as post-walk evidence.

## Decision

Add the post-walk-biased-v4 calibration:

1. Use 75% post-walk snapshot and 25% rest resets during training, retaining
   rest regression coverage while focusing the budget on the sole residual
   failure distribution.
2. Force `fromRestProbability=0` in `post_walk_capture` evaluation, so all five
   runs come from the state bank.
3. Keep `from_rest` evaluation on the deterministic environment without a state
   bank.
4. Preserve the 42-dimensional observation, 10-dimensional action ABI, arm
   trajectory, anchor recovery, training steps, Episode length, seed, and every
   quality gate.
5. Continue initializing from the evidence-bound Capture Checkpoint; do not
   promote the failed v3 Checkpoint into a validated Warm Start.
6. Run one A800 calibration. Only a passing gate may unlock one full-kitchen
   run, and only that passing run may unlock an independent 5/5 gate.

## Evidence boundary

- The 75/25 weighting is a research distribution for the observed failure, not
  a general locomotion claim.
- The v3 Checkpoint, Trace, and state bank remain failure evidence and
  internal-only.
- No `0.20 m` translation, `0.20 m/s` terminal speed, or other behavior gate is
  relaxed.
- Correcting the evaluation distribution may reveal additional failures; that
  is stronger gate validity, not a regression.
