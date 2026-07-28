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

Run the resulting digest-pinned image without installing dependencies:

```bash
KUBECONFIG=/Users/d-robotics/.config/droboticflow/kubeconfigs/poc.config \
  ./scripts/run_a800_h1_locked_runtime_probe.sh
```

The probe records the image source commit separately from the later probe
definition commit. It runs as UID/GID 10001 with a read-only root filesystem,
no ServiceAccount token, no Secret mounts, and one A800. Passing this probe
establishes a locked runtime, not PPO convergence or L3 task success.

Because CCR read access is private, the launcher first creates a tokenless,
CPU-only pre-pull Job in `droboticflow`. Kubelet uses the existing
`imagePullSecret` there to cache the exact image Digest on the selected A800
node. The pre-pull Pod does not mount the Secret, and it is deleted before the
credential-free runtime probe starts in `worldspec-a800-poc`.

Before canonical PPO training, run the exact 8,192-environment allocation and
vectorization preflight:

```bash
KUBECONFIG=/Users/d-robotics/.config/droboticflow/kubeconfigs/poc.config \
  ./scripts/run_a800_h1_capacity_scale_probe.sh
```

This probe compiles a vectorized reset and one zero-action step using the
canonical environment count. It requires finite observations, state, and
reward and fails closed on capacity-overflow diagnostics. It does not update a
policy, save a checkpoint, establish convergence, or satisfy L3; the report is
permanently classified as
`runtimeAcceptance=capacity_scale_preflight` and
`canonicalTrainingStatus=not_executed`.
The first executed A800 report reset 8,192 environments in 189.14 seconds and
completed one batched step in 3.12 seconds with finite
`8192x42` observations, finite `8192x34` qpos, finite `8192x33` qvel, and zero
reported CCD or other capacity overflows. These timings describe one cold
compile/run on the locked node and are not a throughput benchmark.

Run a bounded, non-publishable PPO compile/update smoke after the locked probe:

```bash
KUBECONFIG=/Users/d-robotics/.config/droboticflow/kubeconfigs/poc.config \
  ./scripts/run_a800_h1_ppo_smoke.sh
```

The smoke uses 32,768 timesteps and 256 environments. It proves only that a
non-zero Brax PPO update and one trained-policy inference step execute with
finite values on the exact target model. Its report is permanently classified
as `runtimeAcceptance=research_smoke`, `policyStatus=non_publishable`, and
`canonicalTrainingStatus=not_executed`. It does not write a policy checkpoint,
does not satisfy the 100M profile, and cannot satisfy L3. The launcher also
fails closed when MuJoCo/MJX logs any collision-capacity overflow. The Profile
declares `activeContactsPerEnvironment=16`,
`ccdContactsPerEnvironment=8`, and per-world `njmax=128`. The runtime scales
the aggregate `naconmax` and `naccdmax` by the vectorized environment count.
The 256-environment smoke therefore uses `4096/2048`, while the
8,192-environment canonical run would use `131072/65536`. These choices retain
headroom over the locked upstream H1 reference (`8` contacts per environment
and `njmax=51`) for the added right Robotiq model and remain subject to the
canonical-scale capacity probe.
