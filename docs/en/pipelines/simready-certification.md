---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/pipelines/simready-certification.md
last-verified: 2026-07-28
---

# SimReady certification pipeline

The Chinese document is the normative source; this page is its official translation.

```text
Schema Validate
-> Core Invariants
-> Target Compile
-> Native Load
-> Static Conformance
-> Behavior Tests (L3 only)
-> Reports + Certificate
```

## L2

L2 requires the target runtime to load artifacts natively, resolve every resource, pass static frame/unit/mass checks, and have LossReport cover every lowering decision. “A file was generated” is not L2.

## L3

L3 binds a versioned Task/Behavior Profile, initial state, runtime configuration, and pass thresholds. Behavior tests record at least:

- success/failure and failure category;
- final state and critical predicates;
- numerical anomalies, penetration, NaN, and instability;
- asset, compiler, profile, backend, and hardware versions.

`TaskRunReport` does not replace raw runtime records. Every run binds an independent `RuntimeRecord` digest. The issuer checks TaskProfile, ControlProfile, every PredicateProfile, locked initial state, TargetProfile, BuildManifest, and every RuntimeRecord. A summarized `5/5` cannot substitute for five verifiable traces.

The Reference Predicate Engine consumes canonical evidence rather than backend-native booleans. The issuer recomputes truth, robustness, and confidence from every obligation's canonical `metrics` instead of trusting reported booleans. The first implementation covers `inside`, `stable`, `open`, `closed`, `released`, `upright`, finite state, limits, dangerous collision, and penetration predicates. Missing or non-finite evidence produces `unknown`.

A generated asset may reach L3 while Claims remain Generated/Estimated. MuJoCo and Three.js are v0.1 certification backends. Three.js certifies visual/scene loading and declared interaction, not absent dynamics.

Failures distinguish invalid, compile_failed, target_load_failed, behavior_failed, backend_limited, and unknown. Timeout is never automatically treated as an invalid asset.

## Implemented v0.1 boundary

- The MuJoCo runner verifies Bundle artifacts, loads through real `MjModel.from_xml_path`, and checks finite `qpos/qvel/qacc` after the declared steps.
- The Three.js runner verifies Bundle artifacts, starts the loopback preview and real Chromium, checks GLB load, WebGL, coordinate mapping, and finite bounds, and saves screenshot evidence.
- `worldspec certify` can construct an L2 candidate from bound evidence and only emits/signs it after all digests, Loss coverage, required tests, environment, and artifacts pass.
- The current macOS arm64 local Profiles have each issued an unsigned MuJoCo/Three.js L2 certificate and rejected artifact tampering.
- The repository's locked Linux x86_64 reference Profiles fail on the current Mac by design; they still have no L2 evidence.
- L3 digest/runtime-evidence assessment and issuance are implemented and fail closed without a complete TaskRunReport, all RuntimeRecords, and Predicate evidence.
- No 5/5 H1 kitchen behavior witness exists yet, so the project-level H1 L3 remains incomplete; this implementation is not evidence that H1 passed.
