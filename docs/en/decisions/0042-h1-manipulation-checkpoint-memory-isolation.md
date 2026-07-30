---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0042-h1-manipulation-checkpoint-memory-isolation.md
last-verified: 2026-07-30
---

# ADR-0042: H1 Checkpoint Portfolio GPU-Memory Isolation

The Chinese document is the normative source; this page is its official translation.

## Context

The checkpoint-portfolio-v6 Drobodata A800 job
`worldspec-h1-midterm-xzrb5` executed the PPO training and saved all seven
expected Checkpoints. Before per-candidate evaluation completed, Warp ran out
of GPU memory while switching to the `from_rest` environment and ultimately
could not allocate 48 bytes. The job therefore stopped before the formal
quality gate and is neither a policy failure nor a pass.

The Job used `XLA_PYTHON_CLIENT_PREALLOCATE=false`, but the default BFC
allocator can retain released JAX buffers. Compiled training, post-walk, and
from-rest executables accumulated in one process and left no device memory for
Warp.

## Decision

Add memory-isolated-checkpoint-portfolio-v7:

1. Set `XLA_PYTHON_CLIENT_ALLOCATOR=platform` so released JAX buffers return to
   CUDA.
2. After PPO training, delete training-only environments and teacher-policy
   references, then run `jax.clear_caches()` and garbage collection.
3. Clear compiled caches again when switching from the post-walk suite to the
   from-rest suite and after every Checkpoint candidate.
4. Preserve all v6 Warm Starts, training steps, hyperparameters, state bank,
   seed, candidate set, ranking rules, and quality gates.
5. Record the v6 log, Job/Pod Manifests, and OOM classification as independent
   runtime-failure evidence.
6. Continue to independent Manipulation Policy integration and one
   full-kitchen run only after v7 completes and passes its formal gate.

## Evidence boundary

- v6 proves only that training reached seven saved Checkpoints before an
  evaluation-runtime OOM; it provides no policy-quality result.
- Memory isolation is a runtime correction, not a control, training-objective,
  or gate change.
- The platform allocator may reduce speed but does not change task semantics.
- If v7 again fails before the formal gate, preserve the new evidence and stop;
  a missing result is neither a policy failure nor a pass.
