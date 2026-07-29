---
status: Research
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/research/h1-locomotion-policy.md
last-verified: 2026-07-29
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

The first A800 calibration attempt, `worldspec-h1-calibration-vzndt`, reached
PPO, deterministic evaluation, and local checkpoint packaging, but report
assembly raised `TypeError` by converting shape `(42,)` directly to an
integer. The result marker had not been written and the Pod was cleaned with
the Job, so neither policy quality nor the checkpoint can be recovered or
inferred. This attempt is permanently recorded as
`failed / quality unknown / checkpoint not_recovered`.

After fixing report assembly, `stand-v1` completed a second real-A800 run,
`worldspec-h1-calibration-qxpdh`. Final mean episode length was 124.23 steps,
1.42 times the 87.34 baseline, but it missed the configured 350-step and
2-times gates. All five deterministic stand runs terminated near step 99 with
`fall_height`, with about 1.027 metres of planar drift. The result is therefore
fixed as `completed / quality failed / deterministic stand 0/5`. The report
proves that an internal research checkpoint was generated, but the old
launcher invoked `kubectl cp` only after the Pod completed and the cluster
rejected copying from the exited container. The checkpoint is recorded as
`generated_not_retrieved`. This is valid negative policy-quality evidence, not
a usable policy or permission to start the 100-million-step run.

The initial `stand-v2` preserved the immutable `stand-v1` Profile, raised the
bounded budget to 4,194,304 requested steps and 4,096 environments, strengthened
survival, upright, base-height, and pose shaping, and declared 124.23 as its
baseline. Its first real-A800 job was rejected by Brax before PPO:
`batchSize × numMinibatches = 128 × 16 = 2048` was not divisible by 4,096
environments. This is a configuration failure and contains no policy-quality
evidence; the invalid Profile and log digest are preserved. Core now checks
the constraint before submission, and `stand-v2.1` changes only `batchSize`
to 256 so that `256 × 16` is divisible by 4,096.

Artifact handoff now uses a two-stage handshake: after writing the
report and checkpoint, the Pod enters `artifact_ready`; the launcher copies
the artifact while the Pod remains alive and writes an acknowledgement; only
then may the entrypoint exit. Because this cluster returned `unexpected EOF`
twice for a single `kubectl cp` stream at about 4.7–4.8 MB, the final
implementation uses independent 512-KiB chunks, per-chunk retries, atomic
placement, and final size plus SHA-256 verification against the report.

`stand-v2.1` has now completed on a real A800 and passed every calibration
gate: final mean episode length was 500, a 4.02-times improvement over
`stand-v1`; all five deterministic four-second stand checks passed; maximum
planar drift was about 0.0217 metres; minimum base height was about 0.988
metres; and the log contained no capacity overflow. The internal checkpoint
was completely retrieved in 12 chunks at 6,280,684 bytes with digest
`sha256:fc91edb936de7391b7e075596e5aaa944acc656664cdb820dbb21c149cf7921c`.
See the normative
[`locomotion-calibration.a800.passed.json`](../../../examples/h1-kitchen/locomotion-calibration.a800.passed.json)
report. This evidence remains explicitly
`research_calibration / non_publishable / internal_only`: it permits the next
walking-curriculum experiment, but it is neither canonical 100-million-step
training nor the kitchen-task L3 witness.

## Midterm calibration and formal-training gate

The next stage is frozen as `loaded-track-settle-v1`. It warm-starts from the
internal checkpoint above and restores only observation normalization, policy,
and value networks. Brax 0.14.2 does not restore optimizer state, so the new run
records `optimizerState=reset` and is not described as seamless continuation.

Midterm training uses the final Menagerie H1 plus one right Robotiq 2F-85 for
16,777,216 steps and 4,096 environments. Its gate contains five runs of three
seconds at `0.5 m/s` followed by one second of settling, plus five zero-command
stand regressions. A 100-million-step Job may be created only if mean episode
length is at least 900 and all ten behavior, finite-state, joint, contact, and
capacity checks pass. Any failed run must still return its checkpoint, traces,
and report as `non_publishable`; there is no automatic retry or tuning.

The formal task Profile uses 100,000,000 steps, 8,192 environments, and the
kitchen short-range command distribution, warm-started from the passing
midterm checkpoint. Passing all final ten tests establishes only an internal
`policy_candidate`; it does not prove the complete
walk-open-grasp-place-release-close task at 5/5 and is not kitchen L3 evidence.

The repository now contains the Schema, safe warm-start validation, ten-test
evaluation, Worker lineage gates, bidirectional 512-KiB chunk transport, and
two isolated A800 Job definitions.

### 2026-07-29 midterm execution result

`loaded-track-settle-v1` was executed on one NVIDIA A800-SXM4-80GB. Training
reached 17,203,200 reported steps, the final mean episode length was 972.125,
and all five zero-command stand regressions passed. Forward displacement,
lateral drift, moving-phase velocity tracking, base height, and uprightness
also passed in all five walk-settle tests.

The midterm gate nevertheless failed. Maximum linear speed during the
one-second settling window was 0.4788–0.4883 m/s in the five walking tests,
above the 0.20-m/s limit; maximum angular speed was
0.5349–0.5940 rad/s, above the 0.40-rad/s limit. The formal 100M Job was
therefore not created, and the returned checkpoint remains
`non_publishable / internal_only`. There were no NaNs, joint-limit violations,
capacity overflows, or abnormal-contact diagnostics. The log also contained
two MuJoCo Warp recommendations to increase `ccd_iterations=35`. They were
not CCD-capacity overflows, but their numerical effect must be evaluated
separately before another calibration.

See the normalized failure evidence in
[`locomotion-midterm.a800.failed.json`](../../../examples/h1-kitchen/locomotion-midterm.a800.failed.json).
The complete checkpoint, trace, and raw report remain in the ignored local
`runs/a800/` directory. The frozen plan prohibited automatic tuning or retry
after a failed calibration.
[ADR-0015](../decisions/0015-h1-transition-braking-calibration.md) then selected
option A: retain every original gate, add an explicit 150-step-motion to
50-step-zero-command curriculum and settling rewards, and first run the single
CCD `35 → 50` numerical candidate. The spike must emit no iteration advisory
or capacity overflow over a 4,096-environment, 200-step trace; otherwise
calibration does not start. The CCD spike has now passed on a real A800 with
zero iteration advisories, CCD-capacity overflows, and other capacity
overflows. It proves only that the declared CCD=50 numerical spike is clean;
it is not settling-improvement evidence.

### 2026-07-29 transition-calibration result

`loaded_track_settle_transition` completed 17,203,200 reported steps on the
same class of single A800. Post-walk maximum settling linear speed improved
from 0.4788–0.4883 m/s to 0.4020–0.4377 m/s, and maximum angular speed from
0.5349–0.5940 rad/s to 0.4131–0.4529 rad/s, but all five walking tests still
exceeded the original gates.

At the same time, zero-command stand regression degraded from 5/5 to 0/5:
planar drift reached 0.5112–0.5447 m and settling linear speed was
0.2220–0.2825 m/s. Final mean episode length decreased from 972.125 to
903.4375. The run had no NaNs, joint-limit violations, capacity overflows, or
abnormal-contact diagnostics. The curriculum improved part of the braking
signal but degraded stand retention and overall quality, so the formal gate
failed, no 100M Job was created, and no automatic tuning or retry followed.

See the normalized
[`locomotion-transition.a800.failed.json`](../../../examples/h1-kitchen/locomotion-transition.a800.failed.json)
report.

### A1: stand replay and teacher-action distillation

The next experiment relaxes none of the original gates. It initializes from
the failed transition checkpoint, rebalances sampling to 60% walk/settle
cycles and 40% all-zero-command stand cycles, and uses the passing
`stand-v2.1` deterministic teacher action only during stand replay. The
constraint is implemented as an action-MSE distillation reward and is not
claimed to be strict policy KL. The experiment budget, teacher source, student
source, and reward parameters are locked by
[`locomotion-retention-profile.json`](../../../examples/h1-kitchen/locomotion-retention-profile.json);
the design remains unverified until a real A800 execution.
