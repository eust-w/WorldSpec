---
status: Research
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/research/h1-locomotion-policy.md
last-verified: 2026-07-28
---

# H1 locomotion policy dynamics-domain mismatch

The Chinese document is the normative source; this page is its official translation.

## Executed experiment

The locked Unitree RL Gym H1 TorchScript policy was bound to ten leg
joints/actuators through an explicit adapter. Independent PD hold controlled
the torso and eight arm joints in the composed model, while the Robotiq stayed
open. The test ran on macOS arm64, MuJoCo 3.6.0, and Torch 2.12.0 for four
seconds with a `0.5 m/s` forward command.

The interface layer passed:

```text
policy input: 41
policy output: 10, finite
leg mapping: 10
upper-body hold mapping: 9
gripper mapping: 1
```

The behavior layer failed:

```text
final x: -2.224 m
minimum pelvis z: 0.103 m
minimum upright cosine: -0.162
joint-limit violation samples: 1274
```

The failure report is
[`locomotion-conformance.darwin-arm64.failed.json`](../../../examples/h1-kitchen/locomotion-conformance.darwin-arm64.failed.json).

Running the same observation construction, PD parameters, update rate, and
policy for four seconds on Unitree RL Gym's original H1 model produced:

```text
forward displacement: 1.437 m
lateral drift: 0.017 m
minimum pelvis z: 0.990 m
minimum upright cosine: 0.999
```

The current evidence therefore indicates a **dynamics-domain mismatch between
the policy training model and the articulated Menagerie whole-body model**, not
a TorchScript interface or ten-leg-joint mapping error. The right gripper is
not the sole cause: the unmodified Menagerie H1 also falls under the same
control.

## User decision required

### A. Adapt or retrain locomotion for Menagerie H1 plus the selected gripper (recommended)

- Preserves the selected continuous whole-body dynamics and final L3 meaning.
- Requires Linux GPU training, policy selection, and stability regression.
- Costs the most time and compute but gives the cleanest evidence chain.

### B. Build a hybrid H1 around Unitree RL Gym's native lower-body dynamics

- Reuses the already validated policy and may be faster.
- Requires reconstructing the articulated upper body, mass, inertia, and
  contact calibration.
- Is no longer the unmodified Menagerie H1 and requires a new
  Model/Derivation and behavior certificate.

### C. Switch models after walking or move kinematically during the walking phase

- Produces a visual demo fastest.
- Breaks continuous state/dynamics and cannot satisfy the current physical L3.
- Is acceptable only if the user lowers the acceptance target.

Until a choice is made, the project remains at “composition native-load
passed, policy interface compatible, locomotion behavior failed” and cannot
advance to the kitchen 5/5 L3 state machine.
