---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../zh-CN/decision-register.md
last-verified: 2026-07-29
---

# Decision register

The Chinese document is the normative source; this page is its official translation.

| ID | Decision | Status | ADR |
|---|---|---|---|
| D-001 | Embodied-asset platform; v0.1 accepts three loops together | Accepted | [ADR-0001](decisions/0001-product-scope-and-name.md) |
| D-002 | WorldSpec is a working name; public brand later; do not use SimForge | Accepted | [ADR-0001](decisions/0001-product-scope-and-name.md) |
| D-003 | Repository is source of truth; Chinese normative, English official translation | Accepted | [ADR-0002](decisions/0002-document-and-schema-binding.md) |
| D-004 | JSON + Draft 2020-12 JSON Schema is the normative binding | Accepted | [ADR-0002](decisions/0002-document-and-schema-binding.md) |
| D-005 | Rust Core with Python/TypeScript/WASM bindings | Accepted Design | [ADR-0003](decisions/0003-implementation-and-runtime.md) |
| D-006 | Linux + NVIDIA 80 GB A800/H100 reference generation environment | Accepted Design | [ADR-0003](decisions/0003-implementation-and-runtime.md) |
| D-007 | Mesh, robot, CAD, USD, image, and video inputs | Accepted Design | [ADR-0004](decisions/0004-inputs-and-native-payload.md) |
| D-008 | CAD/USD profile completeness + Native Payload preservation | Accepted | [ADR-0004](decisions/0004-inputs-and-native-payload.md) |
| D-009 | v0.1 certifies MuJoCo/Three.js; OpenUSD does not mean Isaac certification | Accepted | [ADR-0005](decisions/0005-targets-and-certification.md) |
| D-010 | Generated assets default to at most L2; behavior validation may reach L3 without evidence promotion | Accepted | [ADR-0005](decisions/0005-targets-and-certification.md) |
| D-011 | Pluggable generation; TRELLIS.2/Nerfstudio-class reference adapters | Accepted Design | [ADR-0006](decisions/0006-generation-and-corpus.md) |
| D-012 | Corpus uses synthetic assets plus one rights-cleared real kitchen | Accepted Design | [ADR-0006](decisions/0006-generation-and-corpus.md) |
| D-013 | v0.1 surface is CLI/API; Three.js is preview/debug | Accepted | [ADR-0007](decisions/0007-product-surface-and-distribution.md) |
| D-014 | Local CAS manifest/lock/certificate; OCI/Marketplace deferred | Accepted | [ADR-0007](decisions/0007-product-surface-and-distribution.md) |
| D-015 | AGPL-3.0 + commercial license + CLA; legal text pending | Accepted Design | [ADR-0008](decisions/0008-licensing-and-contributions.md) |
| D-016 | “Maximally complete model of reality” | Superseded | Replaced by Profile Complete + Loss Transparency |
| D-017 | Single Scene Tree or field union | Superseded | Replaced by object store, multiple graphs, and Profiles |
| D-018 | Frame-by-frame cross-backend physics equality | Superseded | Replaced by task/behavior tolerance |
| D-019 | World/Task/Benchmark Generation, Registry, Marketplace | Future | [roadmap](roadmap.md) |
| D-020 | Physics inference, collision parameters, and generation cost thresholds | Research | [open questions](research/open-questions.md) |
| D-021 | Rust Axum + Python OCI workers with file CAS + SQLite WAL | Accepted Design | [ADR-0009](decisions/0009-v0.1-execution-baseline.md) |
| D-022 | H1 + Robotiq 2F-85, short walk then drawer/mug task, fixed-scene 5/5 | Accepted Design | [ADR-0009](decisions/0009-v0.1-execution-baseline.md) |
| D-023 | Separate physical, visual-shell, and physical-invariance evidence with joint acceptance | Accepted | [ADR-0009](decisions/0009-v0.1-execution-baseline.md) |
| D-024 | Generation model bundles use a per-file-digest content-addressed read-only cache | Accepted | [ADR-0010](decisions/0010-generation-model-bundles.md) |
| D-025 | H1/Robotiq use locked Menagerie sources and locomotion uses locked Unitree RL Gym; dirty BiGym payloads are not copied | Accepted Design | [ADR-0011](decisions/0011-h1-reference-sources.md) |
| D-026 | H1/Robotiq composition uses a separate profile, complete namespacing, and immutable native payloads; the first L3 case locks one right gripper | Accepted Design | [ADR-0012](decisions/0012-h1-robotiq-composition.md) |
| D-027 | Select A+R: adapt/retrain Menagerie H1 plus one right Robotiq; reject hybrid-model and kinematic-switch routes | Accepted Design | [ADR-0013](decisions/0013-h1-target-dynamics-retraining.md) |
| D-028 | Use MuJoCo Playground v0.2.0, MuJoCo/MJX, Warp, and Brax JAX PPO for H1 retraining; adapt the target composition and retain Orbax as the native output | Accepted Design | [ADR-0014](decisions/0014-h1-mujoco-playground-ppo-engine.md) |
| D-029 | Keep the original midterm gates; add a move-to-zero curriculum and settling rewards, gated by one CCD 35→50 numerical spike before A800 calibration | Accepted Design | [ADR-0015](decisions/0015-h1-transition-braking-calibration.md) |
| D-030 | A1 uses 60% walk/settle, 40% stand replay, and stand-v2.1 teacher-action distillation; run a small A800 calibration without relaxing gates | Accepted Design | [ADR-0016](decisions/0016-h1-stand-retention-distillation.md) |
| D-031 | A2 separates motion and zero-velocity/stand into two frozen policies with a deterministic five-step linear-action-blend supervisor; first run a zero-training A800 probe | Accepted Design | [ADR-0017](decisions/0017-h1-dual-policy-supervisor.md) |
| D-032 | A3 samples real handoff states from the frozen motion policy and trains a separate capture policy; the settle gate measures the final 0.2-second static hold, and failure triggers neither automatic tuning nor a 100M run | Accepted Design | [ADR-0018](decisions/0018-h1-motion-state-capture-policy.md) |
| D-033 | A4 connects frozen Motion, Capture, and Stand policies through a consecutive velocity-stability gate; Capture is capped at 40 steps, handoff blends for five steps, and pure Stand must last at least ten steps; the probe does not start 100M | Accepted Design | [ADR-0019](decisions/0019-h1-phase-aware-supervisor.md) |
| D-034 | A5 freezes the A4 leg Supervisor and adds right-arm Jacobian/impedance plus physical contact for a fixed primitive-kitchen loop; gate one run before 5/5 and forbid hidden grasp constraints or an L3 claim | Accepted Design | [ADR-0020](decisions/0020-h1-fixed-kitchen-integration.md) |
| D-035 | Select A5-R: repair mug support, capacity, and single-step IK; add fixed-base reachability preflight without expanding to whole-body MPC/QP, and proceed to 5/5 only after one passing run | Accepted Design | [ADR-0021](decisions/0021-h1-a5-failure-response.md) |
| D-036 | Select A5-C: freeze A4 leg policies, use planar base, torso, and right-arm QP variables with explicit MuJoCo bias-force feed-forward, and require a CPU/A800 handle-tracking Spike before A5 can be rerun | Accepted Design | [ADR-0022](decisions/0022-h1-a5r-dynamic-control-failure.md) |
| D-037 | Select A5-CI: keep the controller, gates, policies, and scene unchanged; add termination subchannels, joint state, control utilization/saturation, and active-policy evidence, then run exactly one equivalent A800 diagnostic replay; archive and stop on failure | Accepted | [ADR-0023](decisions/0023-h1-a5c-control-spike-failure.md) |
| D-038 | The sole A5-CI Attempt failed in diagnostic post-processing with `KeyError: control`; neither formal diagnostic nor control evidence passed, both old and replay control-termination causes remain unknown, the fix has local/CI evidence only, and no replay, A5/5-of-5, or 100M run is allowed | Accepted | [ADR-0023](decisions/0023-h1-a5c-control-spike-failure.md) |
| D-039 | The user re-authorized corrected A5-CI replay with `formalDiagnosticReplayGate=passed` as the only target; each run uses a new Attempt without automatic retry, post-processing failure must hand off available artifacts first, and a diagnostic pass stops before A5/100M | Accepted | [ADR-0024](decisions/0024-h1-a5ci-corrected-replay.md) |
| D-040 | Attempt-02 completed the A800 replay and identified a `right_hip_yaw` joint-limit termination, but local Receipt creation failed because `datetime` was not imported, so the formal diagnostic handoff still failed; replace Receipt logic with a standalone, unit-tested artifact-identity Finalizer and use a new Attempt | Accepted | [ADR-0024](decisions/0024-h1-a5ci-corrected-replay.md) |
| D-041 | Attempt-03 completed GPU replay, artifact transfer, and Receipt handoff, but the Report `equivalenceAssessment` did not match the frozen Schema, so the formal diagnostic gate still failed; keep the Schema unchanged, correct the implementation, prevalidate it with real artifacts, and use a new Attempt | Accepted | [ADR-0024](decisions/0024-h1-a5ci-corrected-replay.md) |
| D-042 | Attempt-04 completed GPU replay, artifacts, Receipt, diagnostic-completeness checks, and static-equivalence checks, but the existing Trace state `activePolicy=blend` was absent from the diagnostic enumeration, so the formal diagnostic gate still failed; only complete the diagnostic Schema enumeration and replay under a new Attempt | Accepted | [ADR-0024](decisions/0024-h1-a5ci-corrected-replay.md) |
| D-043 | Attempt-05 completed one equivalent diagnostic replay and full artifact handoff on a Drobodata A800 with `formalDiagnosticReplayGate=passed`; the control gate still failed on a `right_hip_yaw` joint limit, the Controller remains `non_publishable`, and execution stopped before A5/5-of-5/100M | Accepted | [ADR-0024](decisions/0024-h1-a5ci-corrected-replay.md) |
| D-044 | Select A5-CF: preserve the A5-C QP, policies, scene, ranges, termination conditions, and quality gates; use `0.05/0.02` task-phase hysteresis plus the validated Capture stability gate and five-step Blend for Motion-to-Stand handoff; gate one A800 Spike without automatic tuning or A5/100M launch | Accepted Design | [ADR-0025](decisions/0025-h1-task-policy-handoff-fix.md) |
| D-045 | A5-CF removed the `right_hip_yaw` handoff violation on A800 but task-phase torso/arm motion caused `fall_height`, so it did not become a control candidate; select A5-CG to lock the base and torso and gate four-joint right-arm QP with explicit bias-force feed-forward once | Accepted Design | [ADR-0026](decisions/0026-h1-dynamic-arm-tracking.md) |
| D-046 | A5-CG kept Stand Policy active with four-joint dynamic-arm isolation on A800, but the low handle target still drove a near-singular elbow posture, backward base slip, and `fall_height`; select A5-CH to move the self-authored task geometry into the observed stable workspace without changing gates or Controller | Accepted Design | [ADR-0027](decisions/0027-h1-ergonomic-task-geometry.md) |

Changing an Accepted decision requires an ADR; editing only implementation prose is insufficient.
