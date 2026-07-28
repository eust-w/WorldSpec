# WorldSpec H1 training backend

This package is the execution boundary for the accepted WorldSpec v0.1
`MuJoCo/MJX + Brax JAX PPO` H1 locomotion route.

It does **not** make the upstream `H1JoystickGaitTracking` environment the
training target. That environment loads a specialized upstream XML, while the
WorldSpec route must train against the digest-bound Menagerie H1 plus one right
Robotiq 2F-85 composition bundle.

The package therefore:

1. validates the profile and immutable composition inventory;
2. derives a training-only XML with a floor and observation/contact sensors;
3. loads that exact derived model through MuJoCo and MJX/Warp;
4. trains a ten-leg-action PPO policy while upper-body joints are held by
   explicit PD control and the gripper command is fixed;
5. exports an Orbax checkpoint archive, a policy manifest, evaluation traces,
   an environment lock, and metrics.

The base installation contains only contract and model-preparation code. The
`runtime` extra is Linux/NVIDIA-specific and pins the selected upstream source
and dependency versions. A successful import or CPU test is not GPU execution
evidence.

Current status: a tokenless compatibility spike, a digest-pinned locked
runtime probe, the exact 8,192-environment allocation probe, and two bounded
PPO research smokes executed on an NVIDIA A800-SXM4-80GB. The
capacity-corrected smoke reported finite training and inference with no
capacity overflow, but only about 87.34 mean evaluation steps. It remains
`research_smoke / non_publishable` and saved no checkpoint.

The package now also defines a separate stand-calibration route with
versioned reward, termination, runtime, quality-gate, and internal-only
checkpoint contracts. `stand-v1` completed on a real A800 and improved mean
episode length from 87.34 to 124.23, but failed every configured quality gate:
deterministic standing was 0/5 and each run terminated at about step 99 for
`fall_height`. The generated research checkpoint was not recovered because
the first launcher attempted to copy it after the Pod had exited. That attempt
is negative policy-quality evidence, not a usable-policy result.

The initial `stand-v2` Profile increased the bounded budget to 4,194,304
requested steps and 4,096 environments, strengthened posture shaping, and used
the completed `stand-v1` result as its declared baseline. Its first A800
attempt failed before PPO because `128 × 16` was not divisible by 4,096.
That exact invalid Profile is preserved; semantic validation now rejects the
configuration before submission. The current `stand-v2.1` changes only the
batch size to 256, making `256 × 16` divisible by 4,096. The launcher now
copies and verifies the checkpoint while the Pod remains alive, then
acknowledges the entrypoint before completion. `stand-v2.1` is still research
until its own A800 report exists. Canonical 100-million-step training,
publishable policy quality, and five-run H1 kitchen L3 evidence remain
unexecuted.
