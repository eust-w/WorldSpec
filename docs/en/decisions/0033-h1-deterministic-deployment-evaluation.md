---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0033-h1-deterministic-deployment-evaluation.md
last-verified: 2026-07-30
---

# ADR-0033: H1 Deterministic Deployment Evaluation and Warm-Start Candidate

The Chinese document is the normative source; this page is its official
translation.

## Context

`loaded_track_settle_task_load_survival` executed 17,203,200 batch-aligned steps
on a real Drobodata A800. The earliest of seven trained Checkpoints passed all
five walk-settle and five loaded-stand tests, but its mean Episode length was
`672.4531 < 900`, so the formal training gate correctly remained failed.

Inspection of the Brax 0.14.2 PPO interface then found that
`deterministic_eval` defaults to `false`. Mean Episode length therefore came
from a policy with sampled exploration, while the ten behavior tests and
deployment use deterministic inference. One formal gate mixed two policy
semantics. Training also evaluated only post-update Checkpoints and omitted the
Warm Start itself, so a degrading run could not preserve the input policy.

## Decision

Add a `loaded_track_settle_task_load_deployment_eval` research stage:

1. Explicitly use `deterministic_eval=true` for Brax Episode evaluation, matching
   behavior-test and deployment inference semantics.
2. Preserve the `900/1000` Episode gate and every speed, drift, attitude,
   termination, and ten-test behavior threshold.
3. Rank the Warm Start and every saved Checkpoint under the same deterministic
   formal gate, packaging only the selected candidate.
4. Bind the Warm Start to the internal Checkpoint selected by the failed
   survival-v3 report. It remains `non_publishable` and is not retroactively
   upgraded by this ADR.
5. Preserve survival-v3 rewards, curriculum, load, teachers, optimizer
   parameters, and seed. This round changes evaluation and candidate retention
   only.
6. If deterministic long-horizon evaluation still fails, change discount/GAE
   horizon under a separate ADR rather than mixing that change into this run.
7. A pass creates only an internal loaded-locomotion candidate and does not
   automatically run A5, 5-of-5, 100M, or kitchen L3.

## Boundaries

- Stochastic-policy evaluation may remain a research metric, but it cannot
  replace the deterministic deployment gate.
- A pass does not prove exploration-policy, real-robot, or randomized-reset
  robustness.
- The historical survival-v3 failure remains unchanged; new conclusions apply
  only to the new Profile, code, OCI, and execution evidence.
