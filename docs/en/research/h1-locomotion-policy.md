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

## Frozen choice

The user selected `A + R`, recorded in
[ADR-0013](../decisions/0013-h1-target-dynamics-retraining.md):

- adapt or retrain locomotion for Menagerie H1 plus one right Robotiq 2F-85;
- preserve continuous whole-body dynamics and the final L3 semantics;
- retain the old Unitree policy only as an interface or initialization candidate.

The following routes are rejected:

- `B`: build a hybrid H1 from Unitree RL Gym lower-body dynamics;
- `C`: switch models or use kinematic translation during locomotion.

The route-decision blocker and the complete absence of GPU execution are
cleared: an isolated tokenless A800 compatibility spike passed JAX GPU
selection, MJX/Warp loading, and one finite reset/step on the derived
H1+right-Robotiq model. A digest-pinned training OCI then passed the same gate
as non-root with a read-only root filesystem and no runtime Secret, so the
runtime is now `locked`.

One 32,768-requested-step, 256-environment A800 PPO research smoke also ran for
the prior capacity Profile. Brax reported 33,280 final steps, about 2,596.7
training steps/s, finite training values, and finite trained-policy inference.
This evidence is fixed as `research_smoke / non_publishable`: it saved no
checkpoint and does not establish policy quality.

A subsequent review of the MuJoCo 3.6 MJX-Warp capacity semantics confirmed
that `naconmax` and `naccdmax` are shared across all vectorized worlds, while
`njmax` is per world. The current Profile therefore uses 16 active contacts
and eight CCD contacts per environment with per-world `njmax=128`. A new
digest-pinned image built from commit `101aff7` and the current Profile's A800
one-step have passed; the prior smoke remains historical evidence only. The
8,192-environment scale probe also passed with finite batched state and zero
capacity overflows. A second, capacity-corrected 32,768-requested-step,
256-environment A800 smoke then completed with 33,280 reported final steps,
about 2,672.75 training steps/s, finite training and inference values, and zero
CCD or other capacity overflows. Its mean evaluation episode length was only
about 87.34 steps. It therefore remains `research_smoke / non_publishable`,
saved no checkpoint, and does not establish a usable policy. The canonical
100-million-step run, a publishable policy, and the kitchen 5/5 L3 behavior
remain unexecuted; the pipeline cannot enter the L3 state machine before those
behavior validations pass.

Before spending the canonical 100-million-step budget, the implementation now
defines a separate `stand-v1` research calibration gate. It uses 1,048,576
requested steps, 2,048 environments, and an exact zero-velocity command, with
versioned survival, upright, base-height, pose, torque, and action-change
shaping. The calibration keeps five strict deterministic stand checks and
separates relaxed training termination from final validation thresholds. Its
checkpoint is fixed as `research_only / internal_only`; even a passing gate
only permits the next curriculum experiment and does not establish canonical
training or L3. This route currently has implementation and a Profile but no
A800 execution report.
