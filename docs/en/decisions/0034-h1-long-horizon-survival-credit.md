---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0034-h1-long-horizon-survival-credit.md
last-verified: 2026-07-30
---

# ADR-0034: H1 Long-Horizon Survival Credit and PPO Drift Control

The Chinese document is the normative source; this page is its official
translation.

## Context

`loaded_track_settle_task_load_deployment_eval` completed a real deterministic
evaluation on a Drobodata A800. The Warm Start reached a mean Episode length of
`771.7578/1000`; the first trained Checkpoint improved to `801.8203/1000` and
passed five walk-settle plus five loaded-stand tests, but remained below the
non-relaxable `900/1000` gate. Later Checkpoints degraded, ending with
`training/kl_mean=0.0401`, while `fall_height` remained the dominant
termination channel.

The previous run used `discounting=0.97` and Brax's default
`gae_lambda=0.95`. That credit horizon is substantially shorter than the
200-step move-settle cycle, and `terminationPenalty=25` enters the return only
at the fall. Evaluation semantics are now correct; changing evaluation again
cannot fix the observed long-duration falls.

## Decision

Add a `loaded_track_settle_task_load_horizon` research stage:

1. Bind the Warm Start to the internal Checkpoint selected by the failed
   deployment-eval-v4 report; restore normalizer, policy, and value while
   resetting the optimizer.
2. Use `discounting=0.995` and `gaeLambda=0.99` so termination credit spans a
   complete move-settle cycle.
3. Increase `terminationPenalty` from `25` to `100` without changing any
   termination condition.
4. Use `clippingEpsilon=0.2` and an `ADAPTIVE_KL` learning rate with
   `desiredKl=0.01`, initial/maximum `1e-5`, and minimum `2.5e-6`.
5. Reduce `entropyCost` to `0.0002` and freeze the restored observation
   normalizer with `normalizeUntilCount=1` to limit post-Warm-Start drift.
6. Preserve the complete A5-CK load, Stand/Capture teachers, command
   distribution, seed, training budget, ten deterministic behavior tests, and
   the `900/1000` gate.
7. Continue ranking the Warm Start and every saved Checkpoint under the same
   formal gate. On failure, retain the strongest evidence but keep it
   `non_publishable`.
8. This stage may create only an internal loaded-locomotion candidate; it does
   not automatically run A5, 5-of-5, 100M, or kitchen L3.

## Boundaries

- This is a long-horizon credit and optimization-stability correction, not
  evidence of randomized-reset or real-robot robustness.
- Freezing normalization is limited to this stage, whose observation ABI and
  task distribution remain unchanged.
- If it still fails, the next round must use the new evidence to choose
  task-distribution specialization or a control-architecture change; lowering
  the `900/1000` gate is forbidden.
