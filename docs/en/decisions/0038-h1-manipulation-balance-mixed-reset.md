---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0038-h1-manipulation-balance-mixed-reset.md
last-verified: 2026-07-30
---

# ADR-0038: H1 manipulation-balance mixed-reset calibration

The Chinese document is the normative source; this page is its official translation.

## Context

The A6-K1 single full-kitchen run still failed during `reach_handle`, so neither
a full-kitchen rerun nor 5/5 is authorized. The first manipulation-balance
calibration, `worldspec-h1-midterm-w2f8x`, failed all ten deterministic tests.
After adding an anchor-recovery command, `worldspec-h1-midterm-dxbgm` improved
the post-walk suite to 4/5, but all five from-rest tests still failed and the
final mean Episode length was `88.0078125/100`.

The five dxbgm from-rest results were nearly identical: maximum displacement was
about `0.1942 m`, inside the `0.20 m` displacement gate, while terminal linear
speed was about `0.5424 m/s`, above the `0.20 m/s` gate. Code and Profile audit
confirmed that training reset exclusively from post-walk Capture Snapshots when
a state bank was present, while 5/10 formal deterministic tests reset from
rest. This is an observed train/evaluation distribution gap, not evidence that
the gates are too strict.

## Decision

Add a mixed-reset-v3 calibration:

1. fix training resets at 50% post-walk Capture Snapshot and 50% rest, matching
   the equal weighting of the two deterministic suites;
2. preserve the 42-dimensional observation ABI, ten-action lower-body ABI,
   right-arm trajectory, anchor-recovery command, training steps, Episode
   length, seed, and every quality gate;
3. emit `state/from_rest_reset` in training metrics so the actual progress
   report proves that mixed sampling occurred;
4. bind the Profile to the dxbgm Report, Checkpoint, Trace, and state-bank
   digests;
5. run exactly one Drobodata A800 calibration. On failure, hand off artifacts
   first and retain `non_publishable`; only a pass authorizes the ADR-0037
   single full-kitchen run;
6. authorize an independent 5/5 run only after the single full-kitchen run
   passes. A mixed-reset pass alone is not kitchen L3.

## Evidence boundary

- 50/50 is a research distribution aligned to the current deterministic suite,
  not a general locomotion conclusion.
- No displacement, speed, attitude, base-height, or Episode-length gate is
  relaxed.
- The failed v2 Checkpoint is archived as evidence and is not a v3 Warm Start.
- Schema, local tests, and image builds cannot replace real A800 behavior.
