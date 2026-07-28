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

A generated asset may reach L3 while Claims remain Generated/Estimated. MuJoCo and Three.js are v0.1 certification backends. Three.js certifies visual/scene loading and declared interaction, not absent dynamics.

Failures distinguish invalid, compile_failed, target_load_failed, behavior_failed, backend_limited, and unknown. Timeout is never automatically treated as an invalid asset.

## Implemented v0.1 boundary

- The MuJoCo runner verifies Bundle artifacts, loads through real `MjModel.from_xml_path`, and checks finite `qpos/qvel/qacc` after the declared steps.
- The Three.js runner verifies Bundle artifacts, starts the loopback preview and real Chromium, checks GLB load, WebGL, coordinate mapping, and finite bounds, and saves screenshot evidence.
- `worldspec certify` can construct an L2 candidate from bound evidence and only emits/signs it after all digests, Loss coverage, required tests, environment, and artifacts pass.
- The current macOS arm64 local Profiles have each issued an unsigned MuJoCo/Three.js L2 certificate and rejected artifact tampering.
- The repository's locked Linux x86_64 reference Profiles fail on the current Mac by design; they still have no L2 evidence.
- valid L3 issuance fails closed until TaskProfile, Predicate, and H1 behavior witnesses are implemented.
