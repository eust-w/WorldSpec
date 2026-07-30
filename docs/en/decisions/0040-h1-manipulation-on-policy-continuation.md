---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0040-h1-manipulation-on-policy-continuation.md
last-verified: 2026-07-30
---

# ADR-0040: H1 Manipulation On-Policy State-Bank Continuation

The Chinese document is the normative source; this page is its official translation.

## Context

The post-walk-biased-v4 Drobodata A800 job
`worldspec-h1-midterm-rf9zh` completed evaluation on the corrected pure
distributions. From-rest behavior remained at `5/5`, but only `3/5` post-walk
initial states passed. The worst state reached `0.9506179 m` maximum base
translation and `3.5268508 m/s` terminal linear speed. Final mean Episode
length also fell from the mixed-reset-v3 value of `94.359375` to `91.828125`.
The 75% post-walk reset bias did not repair the residual failure and made the
worst state substantially less stable.

Held-joint velocity was not an outlier in the failed state, so the evidence
does not support a state-bank velocity inconsistency. A more direct
distribution difference remains: v3 and v4 built their post-walk banks with
the earlier Capture Policy and then trained a new manipulation-balance policy.
The bank's settling segment was not produced by the policy being continued.

## Decision

Add the on-policy-continuation-v5 calibration:

1. Warm start from the internal failed mixed-reset-v3 Checkpoint, restoring the
   normalizer, policy, and value while resetting optimizer state.
2. Keep the frozen formal 100M task-load Motion Policy for the Motion segment.
3. Use the same v3 manipulation-balance policy for the Capture/settling segment
   that creates the 4,096-state bank, aligning the bank with the continuation
   policy initialization.
4. Restore the v3 50% post-walk and 50% from-rest training mixture rather than
   retaining the regressed 75/25 bias.
5. Continue forcing `fromRestProbability=0` for post-walk evaluation and use an
   environment without a state bank for from-rest evaluation.
6. Preserve the 42-dimensional observation, 10-dimensional action, right-arm
   trajectory, anchor recovery, training steps, Episode length, seed, and every
   quality gate.
7. Run one A800 calibration. Only a ten-test pass may unlock integration of an
   independent Manipulation Policy and one full-kitchen run; only that passing
   run may unlock an independent 5/5 gate.

## Evidence boundary

- The v3 Checkpoint is failed `non_publishable / internal_only` evidence. Using
  it as a Warm Start does not upgrade its evidence or rights status.
- “On-policy” only means that the state-bank Capture segment uses the same
  policy as the continuation initialization; the bank is not refreshed online
  during PPO training.
- The v4 Checkpoint, Trace, and bank remain failure evidence and are not used to
  initialize v5.
- No translation, speed, posture, Episode, or kitchen behavior gate is relaxed.
- A v5 pass creates only a manipulation-balance candidate; it is not a
  full-kitchen or L3 result.
