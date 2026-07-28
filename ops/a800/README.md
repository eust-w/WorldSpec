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
