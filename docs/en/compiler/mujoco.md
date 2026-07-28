---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/compiler/mujoco.md
last-verified: 2026-07-28
---

# MuJoCo reference backend

The Chinese document is the normative source; this page is its official translation.

The current reference implementation lowers canonical synthetic rigid bodies, fixed/revolute/prismatic/ball relations, primitive boxes, and resolved OBJ representations from CAS into:

```text
model.xml
compile-summary.json
build-manifest.json
loss-report.json
worldspec.lock.json
```

The minimal cube, an OBJ copied into the Bundle, and two-link/one-joint structures extracted from minimal URDF and MJCF sources have been loaded through local MuJoCo 3.6.0 `MjModel.from_xml_path` and short-stepped. Compiler hierarchy follows the Frame Placement Graph, not the Entity Ownership Tree. A visual-only mesh has collision disabled and reports `unsupported`; a representation without resolvable resources or dimensions produces a diagnostic box and an `approximated` loss; unresolved physics evidence separately reports `resolved-physics-evidence: unsupported`. None of these results is task-certifiable.

GLB-to-MuJoCo mesh conversion, textures, complete inertia, materials, cameras, lights, actuators, sensors, and Native Payload round-trip remain unimplemented. Tendon, equality, plugin, and other unsupported features must be reported rather than silently dropped.

Full L2 still requires a locked-environment ConformanceReport, resource/unit/frame/mass-inertia checks, and a certificate. The current native-load smoke test is not an issued L2. L3 subsequently runs selected rigid-body behaviors such as free fall, rest, ramp, joint limits, drawer motion, or grasp holding.

No frame-by-frame trajectory equivalence with other backends is promised; only declared tests and tolerances are certified.
