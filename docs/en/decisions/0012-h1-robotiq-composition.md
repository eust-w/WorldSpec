---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0012-h1-robotiq-composition.md
last-verified: 2026-07-28
---

# ADR-0012: Traceable H1/Robotiq composition

The Chinese document is the normative source; this page is its official translation.

## Decision

WorldSpec does not modify the Menagerie H1 or Robotiq source trees. The
composer re-verifies
[`h1-kitchen.lock.json`](../../../third_party/h1-kitchen.lock.json), copies the
immutable native payloads, deterministically namespaces Robotiq bodies, joints,
meshes, materials, default classes, tendons, equality constraints, and
actuators, and mounts the result on the H1 body named by a separate
CompositionProfile.

The profile supports one or two Robotiq 2F-85 grippers. v0.1 currently provides
one **experimental right-hand, single-gripper candidate**:

```text
parent body: right_elbow_link
translation: [0.28, 0, -0.015] m
rotation wxyz: [0.70710678, 0, 0.70710678, 0]
```

The transform maps gripper-local `+Z` to H1 forearm-local `+X`, with the mount
frame at the distal endpoint of the H1 elbow collision capsule. An independent
mount frame wraps the native Robotiq root body without overwriting its source
transform. The TCP binds the upstream `pinch` site and is resolved through the
composed frame graph. The mount remains an `estimated` hypothesis, not a
manufacturer-declared interface or measured TCP. This candidate does not
freeze the final task to one gripper; the left, right, or dual-gripper choice
remains a user decision for the final Task/ControlProfile.

## Evidence obtained

On macOS arm64 with Python 3.12.9 and MuJoCo 3.6.0, the locked-source bundle
was loaded through `MjModel.from_xml_path` and stepped 20 times:

```text
bodies=36, joints=28, actuators=20, meshes=29, sites=2
initial finite=true, after finite=true
```

Repeated composition produced the same bundle digest,
`sha256:07e8122f3c922c1ae65e3eca17c34af4cb7a5e92dc926ecb07da9fdbda95938b`.
Tampering with one mesh failed integrity checking and blocked native loading.
The sanitized report is
[`examples/h1-kitchen/native-load-conformance.darwin-arm64.json`](../../../examples/h1-kitchen/native-load-conformance.darwin-arm64.json).

## Evidence boundary

This evidence only establishes that the candidate composition:

- has traceable sources and licenses;
- has collision-free namespaces;
- produces deterministic artifacts and rejects tampering; and
- loads and takes short steps in the current local MuJoCo environment.

It does not establish:

- correct mounting-plate geometry, TCP, or reachability;
- Unitree RL Gym policy compatibility with the composed dynamics;
- stable walking, balance, or kitchen-task completion;
- Linux x86_64, A800/H100, or real-robot validation; or
- whether the final task should use one or two grippers.
