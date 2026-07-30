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
