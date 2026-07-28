---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0013-h1-target-dynamics-retraining.md
last-verified: 2026-07-28
---

# ADR-0013: H1 target-dynamics retraining route

The Chinese document is the normative source; this page is its official translation.

## Decision

The user selected `A + R`:

- `A`: adapt or retrain locomotion for the locked Menagerie H1 and selected
  gripper; do not build a hybrid H1 and do not switch models between locomotion
  and manipulation;
- `R`: the first L3 case uses one right-hand Robotiq 2F-85.

Locomotion training must target the exact composition bundle selected by
[`composition-profile.json`](../../../examples/h1-kitchen/composition-profile.json).
The locked Unitree RL Gym policy is retained only as an interface reference,
initialization candidate, or distillation candidate. Its failed target-model
behavior must not be treated as teacher truth or success evidence.

The reference route is PPO on MuJoCo/MJX with four gated stages:

```text
Stand
→ Velocity Tracking
→ Loaded Velocity Tracking (right Robotiq)
→ Stop and Settle (manipulation-ready posture)
```

[ADR-0014](0014-h1-mujoco-playground-ppo-engine.md) locks the concrete training
engine, source version, adapter boundary, and native artifact type.

Domain randomization remains disabled until the nominal model passes. A
publishable policy must bind the target bundle, CompositionProfile, Source Lock,
OCI digest, Python package lock, training result, and evaluation traces. The
training worker fails closed when its locked runtime, GPU, native-load evidence,
or output contract is missing.

## Implemented boundary

- `train` Job operation and CLI entry point;
- versioned LocomotionTrainingProfile and TrainingResult schemas;
- gates for target bundle, right single gripper, native-load report, OCI, and
  package-lock bindings;
- an explicit output contract for the locked external
  `worldspec_h1_training` package;
- a `blocked / not_executed` result while the Linux GPU runtime is unlocked.

This does not mean PPO training has run or that a new policy exists. The current
profile runtime remains `planned`; real A800/H100 training and five consecutive
evaluations remain acceptance blockers.

## Consequences

- continuous whole-body physics is preserved from walking through manipulation;
- training cost is higher than a hybrid model or kinematic translation;
- Menagerie/MJX compatibility, hyperparameters, and GPU cost require a real spike;
- changing the gripper, mount transform, or target bundle digest invalidates all
  prior training evidence.
