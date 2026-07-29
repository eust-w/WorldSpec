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

The first capacity-corrected A800 smoke completed in 232.44 seconds. Brax
reported 33,280 final steps and 2,672.75 final training steps/s; trained-policy
inference was finite, and CCD/other capacity-overflow counts were zero. The
mean evaluation episode length was only 87.34 steps, so the run is runtime
evidence with poor policy-quality evidence, not a training benchmark or a
usable-policy result.

Before committing the 100-million-step budget, run the bounded stand
calibration:

```bash
KUBECONFIG=/Users/d-robotics/.config/droboticflow/kubeconfigs/poc.config \
  ./scripts/run_a800_h1_locomotion_calibration.sh
```

The preserved `stand-v1` Profile used 1,048,576 requested timesteps and 2,048
environments with an exact zero command. It completed on an A800, improved
mean episode length from 87.34 to 124.23, but failed the episode-length,
improvement, and 5/5 deterministic stand gates. Its generated checkpoint was
not recovered because the first launcher attempted `kubectl cp` after Pod
completion.

The initial `stand-v2` job used 4,194,304 requested timesteps and 4,096
environments but failed before PPO because `batchSize=128` and
`numMinibatches=16` did not satisfy Brax's divisibility requirement for 4,096
environments. That Profile and real A800 configuration-failure evidence are
preserved. The current `stand-v2.1` changes `batchSize` to 256 and adds a
local semantic preflight for the constraint. It retains the exact zero command
and strengthened versioned survival, upright, base-height, pose, torque, and
action-rate shaping. The launcher copies the checkpoint at the
`artifact_ready` stage while the Pod is still running, acknowledges the copy,
and fails closed if the handoff does not complete.

`stand-v2.1` completed on a real A800 with final mean episode length 500,
4.02-times improvement over `stand-v1`, and 5/5 deterministic four-second
stand passes. Its internal checkpoint was transferred in 12 verified 512-KiB
chunks; the final size was 6,280,684 bytes and its SHA-256 matched the report.
The result and checkpoint remain
`research_calibration / non_publishable / internal_only`; passing the gate
permits the next curriculum experiment but does not establish canonical
training or L3. The launcher acknowledges the Pod only after checking the
reported digest and fails closed on collision-capacity overflows.

The gated next stage is launched with:

```bash
./scripts/run_a800_h1_midterm_then_training.sh
```

The launcher first uploads the digest-bound stand report and checkpoint in
independent 512-KiB chunks. The `loaded-track-settle-v1` Job trains for
16,777,216 steps and evaluates five walk/settle plus five stand-regression
runs. A failed gate returns evidence and exits without creating the formal
Job. A passing gate automatically starts the 100-million-step, 8,192-
environment Job with the midterm checkpoint as a warm start. Both Jobs use the
same `input_ready -> running -> artifact_ready -> artifact_copied` contract,
one GPU, no runtime Secret or PVC, a non-root user, and a read-only root
filesystem.

The formal result is evidence-first: checkpoint, policy manifest, traces,
environment lock, and report are copied and digest-verified even when the ten
final tests fail. Only ten passing tests produce `policy_candidate`; the
artifact remains internal and does not claim the full kitchen L3 task.

The first `loaded-track-settle-v1` A800 run failed only the unchanged settling
linear/angular-speed gates. The selected follow-up is therefore a separate,
fail-closed transition experiment:

```bash
./scripts/run_a800_h1_ccd_iterations_spike.sh

WORLD_SPEC_CCD_SPIKE_REPORT=runs/a800/<ccd-job>/ccd-iterations-spike-report.json \
  ./scripts/run_a800_h1_transition_calibration.sh
```

The first command tests only the predeclared `ccd_iterations=50` candidate over
4,096 environments and 200 steps. The second command refuses to run unless
that report is `passed` and clean. It warm-starts from the frozen failed
midterm checkpoint, uses a 150-step move plus 50-step zero-command curriculum,
and retains every original quality gate. Neither command retries or adjusts
parameters automatically.

After the passing A3 Capture Policy is available, run the evaluation-only A4
phase-aware supervisor probe:

```bash
./scripts/run_a800_h1_phase_aware_supervisor_probe.sh
```

The probe loads the frozen transition-v2 motion checkpoint, the passing A3
capture checkpoint, and the passing `stand-v2.1` checkpoint. It allows the
Capture Policy at most 40 control steps and requires five consecutive samples
below the `0.12 m/s` linear and `0.20 rad/s` angular stability thresholds
before a five-step Capture-to-Stand blend. A passing walk test must contain at
least ten pure Stand steps. The job performs no PPO update and never starts
the 100M run; even a pass is only an internal `supervisor_candidate`, not L3.
