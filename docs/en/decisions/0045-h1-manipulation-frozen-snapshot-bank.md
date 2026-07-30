---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0045-h1-manipulation-frozen-snapshot-bank.md
last-verified: 2026-07-30
---

# ADR-0045: Reuse the frozen v11 snapshot bank for manipulation calibration

The Chinese document is the normative source; this page is its official
translation.

## Status

Accepted Design.

## Context

After correcting v12 source-stage recognition, Job
`worldspec-h1-midterm-jnj6z` entered real A800
`manipulation_portfolio_training`. Before PPO began, snapshot generation
reported:

```text
Frozen motion/capture teachers terminated before snapshot capture.
```

v12 had used the v11-selected Checkpoint both as the training Warm Start and as
the Capture teacher. That Checkpoint is a manipulation-balance policy trained
on existing post-walk states, not a policy evidenced to stabilize the
motion-to-Capture handoff. Conflating these roles was unsupported.

v11 already delivered a complete bank with 4,096 finite states,
`qpos/qvel/last_action` arrays, and `terminatedSnapshotCount=0`. The same bank
was used for v11 seven-candidate training and all fourteen formal evaluations.

## Decision

Add `unbounded-recovery-frozen-bank-checkpoint-portfolio-v13`:

- retain the v11-selected Step 4,915,200 Checkpoint as the training Warm Start;
- preserve unbounded recovery costs, the 50/50 training mixture, control
  ranges, candidate count, seeds, and every quality gate;
- stop treating the manipulation-balance Checkpoint as a Capture teacher;
- upload the v11 bank as a fifth read-only input;
- before launch, verify source Job, Report Digest, Blob Digest, size, array set,
  shapes, finite values, and `terminatedSnapshotCount=0`;
- copy the input Blob byte-for-byte into this run's artifacts so training and
  all fourteen isolated evaluations consume one Digest.

This makes the v13 post-walk training distribution identical to v11 and limits
the sole experimental variable to the ADR-0044 unbounded recovery costs.

## Gates

- v13 must still pass post-walk `5/5`, from-rest `5/5`, and the frozen Episode
  gate.
- A v13 pass unlocks only one full kitchen run.
- Only a passing full-kitchen single run unlocks an independent kitchen `5/5`.
- This correction authorizes no new 100M training, automatic retry, gate
  relaxation, or L3 claim.
