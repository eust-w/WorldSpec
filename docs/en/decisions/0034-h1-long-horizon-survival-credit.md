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

## Execution result

On 2026-07-30, this stage executed on one Drobodata A800 using locked commit
`7a2081e62c41a8e31dae796d658be2a68349a537` and OCI image
`sha256:c5b801f45d9cfa6de2a210cb25a38ddf242639ed3aa63acb6490a274467dbf69`.
The run reported `17,203,200` steps and evaluated eight candidates. Six
consecutive saved candidates passed the formal gate starting at step
`4,915,200`. Deterministic ranking selected the step-`12,288,000` checkpoint
at `996.0078/1000` mean Episode length; the terminal checkpoint remained at
`991.3672/1000`, so the prior late collapse did not recur.

All five walk-settle and five loaded-stand regression tests passed for the
selected checkpoint. Walking covered `1.1849–1.2122 m`, velocity-tracking RMSE
was `0.1863–0.1872 m/s`, and the final measurement-window speed stayed below
`0.0911 m/s` linear and `0.0940 rad/s` angular. Minimum base height exceeded
`0.9882 m`, minimum upright cosine exceeded `0.9946`, and there were no NaNs,
joint-limit violations, capacity overflows, or abnormal contacts.

The formal training gate is therefore `passed`, while the policy remains
`non_publishable / internal_only`. The checkpoint digest is
`sha256:d5ddb461d27366e6959c22dac928d81ab0039b55030427c80e9ab6ffb09b1943`
and the Trace digest is
`sha256:611d6af92c827491b057cfb217705bfeed9b128aba96acddb23c88bcbfc6f87c`.
This closes only the task-load locomotion midterm gate; it did not
automatically start 100M, A5, 5-of-5, or kitchen L3. See the normalized
[`locomotion-task-load-horizon.a800.passed.json`](../../../examples/h1-kitchen/locomotion-task-load-horizon.a800.passed.json)
report.
