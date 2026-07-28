---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0014-h1-mujoco-playground-ppo-engine.md
last-verified: 2026-07-28
---

# ADR-0014: H1 MuJoCo Playground PPO training engine

The Chinese document is the normative source; this page is its official translation.

## Decision

H1 target-dynamics retraining uses this locked stack:

- MuJoCo Playground `v0.2.0`, commit
  `124a73fa3303f75a62f8fe04d329b829ed0ebdfb`;
- MuJoCo `3.6.0` and MJX;
- the MJX Warp physics implementation;
- the Brax JAX PPO trainer;
- `H1JoystickGaitTracking` only as a reference task and hyperparameter baseline;
- `worldspec_h1_loaded_velocity_v1` as the target composition-bundle adapter.

[`h1-training.lock.json`](../../../third_party/h1-training.lock.json) locks the
source and key-file digests.

The following layers remain distinct:

```text
Brax JAX PPO
→ optimization algorithm and training loop

MJX Warp
→ batched physics implementation
```

They must not be collapsed into the ambiguous label “Warp PPO.”

## Adapter boundary

The upstream H1 environment uses its own training XML and therefore cannot prove
that the locked WorldSpec Menagerie H1 plus right Robotiq composition is
trainable. WorldSpec adds a target-bundle adapter that:

- never modifies the source bundle;
- adds a floor, foot sites, contact sensors, and posture sensors to a derived
  training model;
- binds the target composition digest, controlled joints, held posture, and
  gripper command;
- emits a derivation manifest;
- requires a real MuJoCo load before MJX/Warp preflight.

## Output contract

The normative Brax JAX PPO output is an Orbax/JAX checkpoint, not a TorchScript
file. A successful training result must contain:

- a deterministic Orbax checkpoint archive;
- a policy manifest;
- five nominal evaluation traces;
- an environment lock.

ONNX, TorchScript, or other deployment formats are separate conversion steps
that require their own validation evidence.

## Current evidence status

The framework decision and source lock are `Accepted Design`; the target runtime
is now `locked`:

- the Linux x86_64 OCI image is digest-pinned;
- the A800 MJX/Warp one-step preflight passed;
- PPO has not run;
- no new policy exists;
- the target bundle has not passed five consecutive evaluations.

This ADR is not evidence of a GPU run, a usable policy, or L3 acceptance.

## Consequences

- the route reuses stable MuJoCo Playground APIs and H1 experience;
- the target composition still requires a dedicated environment adapter and real
  training;
- the complete Playground, JAX, MJX, Warp, Brax, and CUDA version set must enter
  the runtime lock;
- Ampere runs must request highest matrix-multiplication precision and fail
  preflight when configured incorrectly;
- changing the framework version, physics implementation, target bundle, or
  control mapping invalidates training evidence.
