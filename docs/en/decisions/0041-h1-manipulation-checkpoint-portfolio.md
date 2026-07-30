---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0041-h1-manipulation-checkpoint-portfolio.md
last-verified: 2026-07-30
---

# ADR-0041: H1 Manipulation Checkpoint Portfolio Gate

The Chinese document is the normative source; this page is its official translation.

## Context

The on-policy-continuation-v5 Drobodata A800 job
`worldspec-h1-midterm-hftjt` completed with a final mean Episode length of
`97.453125/100`. From-rest tests passed `5/5`, but post-walk initial states
passed only `3/5`. The formal gate therefore failed and the Checkpoint remains
`non_publishable / internal_only`.

The returned Checkpoint archive contains seven training stages:

```text
2,457,600
4,915,200
7,372,800
9,830,400
12,288,000
14,745,600
17,203,200
```

The existing implementation ran the ten deterministic behavior gates only on
the terminal `17,203,200` stage. An earlier stage may satisfy every gate before
the terminal stage regresses, so terminal-only evaluation does not audit the
candidate evidence already retained by training.

## Decision

Add checkpoint-portfolio-v6:

1. Preserve the v5 Warm Start, Motion/Capture policies, state-bank generation,
   50/50 reset mixture, PPO hyperparameters, seed, observation/action ABI, and
   every quality gate.
2. Evaluate all seven numeric Checkpoints against the same 4,096-state bank,
   pure post-walk environment, from-rest environment, and ten deterministic
   gates.
3. Rank candidates by formal-gate success first, then passed-test count, mean
   Episode length, and finally the earlier training step. No failed candidate
   may receive upgraded evidence.
4. Export only the selected numeric stage in `midterm-checkpoint.zip`, while
   retaining all seven gate summaries in the Report.
5. The existing two-Checkpoint transport cannot independently replay the
   current archive without adding an unfrozen input. Run one integrated A800
   calibration so all candidate evidence shares the exact run and state bank.
6. Only a selected candidate that passes all ten tests and the mean-Episode
   gate may be integrated as an independent Manipulation Policy for one
   full-kitchen run. Only that passing run may unlock independent 5/5.

## Evidence boundary

- This decision does not relax a gate or change the training distribution or
  hyperparameters.
- Ranking cannot promote a `9/10` stage or one below the mean-Episode gate.
- The v5 Report, Checkpoint, Trace, and state bank remain preserved failure
  evidence.
- A v6 pass creates only an internal manipulation-balance candidate, not a
  full-kitchen, 5/5, or L3 result.
- If every stage fails, this route stops at calibration without automatic
  tuning or a kitchen launch.
