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

One 32,768-requested-step, 256-environment A800 PPO research smoke also ran.
Brax reported 33,280 final steps, about 2,596.7 training steps/s, finite
training values, and finite trained-policy inference. After scaling `naconmax`
per environment, both CCD and contact-capacity overflow counts were zero. This
evidence is fixed as `research_smoke / non_publishable`: it saved no checkpoint,
and its mean evaluation episode length of about 87.75 steps does not establish
policy quality. The canonical 100-million-step run, a new publishable policy,
and the kitchen 5/5 L3 behavior remain unexecuted. The pipeline cannot enter
the L3 state machine before those behavior validations pass.

A subsequent review of the MuJoCo 3.6 MJX-Warp capacity semantics confirmed
that `naconmax` and `naccdmax` are shared across all vectorized worlds, while
`njmax` is per world. The current Profile therefore uses 16 active contacts
and eight CCD contacts per environment with per-world `njmax=128`. A new
digest-pinned image has been built from commit `101aff7`; the prior smoke and
runtime reports remain historical evidence only. A new one-step, an
8,192-environment scale probe, and a new smoke still require execution for the
current Profile.
