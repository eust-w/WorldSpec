---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0043-h1-manipulation-process-isolation.md
last-verified: 2026-07-30
---

# ADR-0043: H1 Manipulation Training/Evaluation Process Isolation

The Chinese document is the normative source; this page is its official translation.

## Context

The memory-isolated-checkpoint-portfolio-v7 Drobodata A800 job
`worldspec-h1-midterm-rfkl4` trained through step 17,203,200 and saved all seven
Checkpoints. The platform allocator, `jax.clear_caches()`, and garbage
collection still did not release every JAX/XLA/Warp device context in the same
Python process. Warp failed to allocate 100,663,296 bytes when candidate
evaluation switched to the `from_rest` environment. The formal manipulation
balance gate was never evaluated, so this is not a policy-quality failure.

## Decision

Add process-isolated-checkpoint-portfolio-v8:

1. The first Python/CUDA process only builds the state bank, trains seven
   Checkpoints, persists exact Progress Records and a binding manifest, then
   exits normally.
2. The shell starts a fresh Python/CUDA process only after the first process
   succeeds.
3. The second process read-only verifies the Profile, input Checkpoints, state
   bank, candidate steps, and digests before running the unchanged ten tests.
4. A Canonical Digest manifest binds the process boundary; any file, Profile,
   or candidate-set drift fails closed.
5. Preserve the Warm Start, teachers, training steps, environment scale, seed,
   candidate ranking, and every quality gate.
6. Preserve the v7 log and Job/Pod Manifests as independent runtime-failure
   evidence. Do not automatically launch one full-kitchen run or 5/5.

## Evidence boundary

- v7 proves real A800 training completed and exposed another same-process
  device-lifetime defect; it provides no policy-quality result.
- Process isolation changes runtime lifetime only, not the learning problem,
  controller semantics, or acceptance gates.
- v8 becomes a Manipulation Policy candidate only after complete artifact
  handoff and a passing formal gate.
- If v8 stops before the formal gate, it remains a runtime failure.

## v8 outcome and v9 correction

The v8 job `worldspec-h1-midterm-j6zgw` completed the real 17,203,200-step
training run, saved seven Checkpoints, exited the training process, and started
the fresh evaluation process. Evaluation stopped before loading any candidate
because the Brax API import path was wrong:
`brax.training.running_statistics` must be
`brax.training.acme.running_statistics`. No candidate test ran, so this result
has no policy-quality meaning.

v9 changes only that import path and adds a source regression assertion. The
process boundary, training, candidates, seed, and quality gates remain
unchanged.

## v9 outcome and v10 correction

The v9 job `worldspec-h1-midterm-lj499` again completed the real A800 training
run with seven Checkpoints and entered the fresh evaluation process. Before any
candidate test, the fail-closed model materializer refused to overwrite
`/scratch/h1-training-model/target-bundle`, which had been left by the training
process. This error still provides no policy-quality result.

v10 changes only the evaluation process to use the independent
`/scratch/h1-training-model-evaluation` directory. Training, candidates,
inputs, seed, ranking, and every quality gate remain unchanged.

The first v10 image came from the pre-lock `cb578b8` commit, so runtime code
still bound the old `runtimeFailure` while the source archive contained the new
binding. Job `worldspec-h1-midterm-xpqpv` correctly failed closed before
training. The locked replacement image is built from `0b7cd20`; only the
Profile OCI Digest changes. This configuration failure has no policy-quality
meaning.

## v10 outcome and v11 suite isolation

Locked v10 job `worldspec-h1-midterm-v99rh` completed real A800 training, saved
seven Checkpoints, and entered a fresh evaluator using the independent derived
model directory. After the first candidate completed `post_walk_capture`,
switching to the `from_rest` environment still accumulated JAX/XLA/Warp device
state in the same evaluation process until even a 48-byte device allocation
failed. The formal gate was not evaluated, so this remains a runtime failure,
not a policy-quality result.

v11 gives every candidate and every suite an independent CUDA lifetime. The
seven candidates each run `post_walk_capture` and `from_rest`, producing
exactly 14 read-only results bound to the Portfolio State Digest, Step, and
Suite. A final CPU-only aggregator rejects missing, extra, or lineage-drifted
results before applying the unchanged candidate ordering and formal quality
gate. Training inputs, Checkpoints, state bank, seed, evaluation traces, and
every gate remain unchanged.

## Formal v11 outcome

Job `worldspec-h1-midterm-hnhb6` completed seven-candidate training, all 14
isolated suites, CPU aggregation, and verified artifact handoff on a real A800.
The runtime defect is closed, but the formal manipulation-balance gate failed.
All seven candidates passed `from_rest` 5/5; their `post_walk_capture` results
were 2/5, 4/5, 3/5, 4/5, 4/5, 4/5, and 4/5. The frozen ordering selected Step
4,915,200. Its second post-walk trajectory terminated with `fall_height` at
step 99/100, reaching a 0.466 m minimum base height and 0.749 m maximum lateral
drift.

This is a real policy-quality failure, not a runtime failure. The Checkpoint is
preserved only as `internal_only / non_publishable` failure evidence. One
full-kitchen run, kitchen 5/5, and 100M training remain prohibited. The next
design stage must improve post-walk hard-state control or training without
relaxing any existing gate.
