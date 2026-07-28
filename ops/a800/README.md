# Drobodata A800 validation

This directory defines an isolated, evidence-first validation route for the
WorldSpec H1 MuJoCo/MJX runtime.

The first job is intentionally a compatibility spike, not PPO training. It:

1. creates a deterministic Git archive from the exact published WorldSpec
   commit, verifies its SHA-256 inside the Pod, and never mounts repository
   credentials;
2. installs the frozen runtime dependency graph in an ephemeral filesystem;
3. reconstructs the digest-bound H1 plus right Robotiq bundle;
4. loads the derived model through MuJoCo and MJX/Warp on one A800;
5. executes one zero-action environment step and reports finite-state evidence.

Run it with:

```bash
KUBECONFIG=/Users/d-robotics/.config/droboticflow/kubeconfigs/poc.config \
  ./scripts/run_a800_h1_runtime_spike.sh
```

Evidence is written under `runs/a800/`, which is intentionally ignored by Git.
The spike report uses `runtimeAcceptance=executed_not_locked`: successful
runtime installation is not a substitute for a digest-pinned final OCI image.

The namespace is separate from `amdcompetition-poc`, uses a tokenless Service
Account, requests one GPU, and has no PVC or credential mounts.

After the compatibility spike passes, build the digest-pinned training image:

```bash
KUBECONFIG=/Users/d-robotics/.config/droboticflow/kubeconfigs/poc.config \
  ./scripts/build_a800_h1_training_image.sh
```

The build uploads only the exact published Git archive to the existing
Drobodata build-context PVC. Its tokenless Kaniko Pod runs in the
`droboticflow` namespace and mounts the existing registry Secret read-only.
It drops all default Linux capabilities, then adds only `CHOWN`,
`DAC_OVERRIDE`, `FOWNER`, `SETGID`, and `SETUID`, which Kaniko needs to restore
base-image file ownership and modes and to enter the Dockerfile-declared user
while executing build layers.
The Secret is never copied into `worldspec-a800-poc`, the repository, or the
local report. The build context and Job are removed after evidence capture.
The Dockerfile must never recursively change `/workspace`: that path is the
shared build-context PVC in Kaniko. Runtime input and output directories are
provided as dedicated volumes by runtime Jobs instead.
