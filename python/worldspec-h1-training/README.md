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

Current status: source and API implementation exist; no OCI digest is locked,
no A800/H100 run has been performed, and no policy or five-run success evidence
exists.
