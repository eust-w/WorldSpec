---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0035-h1-formal-100m-training-result.md
last-verified: 2026-07-30
---

# ADR-0035: H1 formal 100M training result and stand-regression failure

The Chinese document is the normative source; this page is its official translation.

## Context

The long-horizon calibration in ADR-0034 selected an internal Checkpoint that
passed the midterm gate. The formal stage used that Checkpoint as a PPO Warm
Start on the final H1 plus right-hand Robotiq load model. It required all five
walk-settle tests and all five zero-command stand-regression tests to pass.

The first formal Job, `worldspec-h1-midterm-dc4g6`, trained through
`100,270,080` steps. Its evaluator then loaded all candidate Checkpoints at
once and hit a Warp CUDA OOM. Because the Job used ephemeral storage and had
not packaged the Checkpoints before evaluation, this run proves that the
training loop completed but does not provide a recoverable policy or a valid
quality result.

The implementation was then changed to:

1. evaluate only the terminal Checkpoint in the formal Profile;
2. package all training Checkpoints and a recovery manifest before behavior evaluation;
3. disable JAX preallocation of most GPU memory;
4. hand off the report, terminal Checkpoint, Trace, and log regardless of quality.

The corrected source commit is
`81df2ed0dc81c2f866a5c2ed2ce4fa897bd85a15`, and the runtime image digest is
`sha256:fda98c9a9623fdd6be96bfdb551b53257d10e3950c85cff1094052546b4381d1`.

## Execution result

The second Job, `worldspec-h1-midterm-cdbm5`, completed on one Drobodata
NVIDIA A800-SXM4-80GB:

- maximum training step: `100,270,080`;
- terminal mean episode length: `996.4844/1000`, passing the `900/1000` gate;
- walk-settle suite: `5/5` passed;
- zero-command stand-regression suite: `0/5` passed;
- NaN, joint-limit, contact-capacity, and abnormal-contact diagnostics: all zero.

Walk-settle forward displacement was `1.0536–1.0843 m`, tracking RMSE was
`0.2200–0.2227 m/s`, and both linear and angular velocity in the final
`0.2 s` window remained within their gates.

Zero-command stand planar drift was `0.3140–0.3239 m`, above the frozen
`0.20 m` maximum. Height, uprightness, terminal speed, and numerical stability
otherwise passed. The failure is therefore position retention while standing,
not a fall, numerical fault, or artifact-transfer failure.

The terminal Checkpoint, Trace, report, and log were transferred and verified
by SHA-256. The sanitized summary is
[`locomotion-task-load-formal.a800.failed-summary.json`](../../../examples/h1-kitchen/locomotion-task-load-formal.a800.failed-summary.json).

## Decision

1. The formal training gate remains `failed`; the policy remains
   `non_publishable / internal_only`.
2. The `0.20 m` stand-drift gate is not relaxed, and the `5/5` walk result is
   not promoted into a complete policy candidate.
3. This run proves completed 100M execution and recoverable Checkpoint
   delivery. It does not prove a Controller Candidate, the full kitchen task,
   end-to-end 5/5, or L3.
4. The Schema accepts both the historical `deterministic_gate_rank_v1` and the
   formal `terminal_gate_v1` report modes. This compatibility fix changes no
   historical quality conclusion.
5. The frozen plan forbids automatic tuning or retry after a quality failure.
   Any further GPU run requires a new ADR selecting a control structure or
   training objective.

## Decision required

Only a new route may continue; blindly rerunning this Profile is not allowed:

- use the terminal 100M Checkpoint only as a motion policy under the validated
  Motion → Capture → Stand Supervisor;
- retain a single PPO policy but add explicit zero-command displacement state
  and reward, then run a newly gated small calibration;
- stop the H1 L3 route and complete other WorldSpec v0.1 loops first.

No route may retroactively label this failed policy as publishable.
