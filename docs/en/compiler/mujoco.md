---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/compiler/mujoco.md
last-verified: 2026-07-28
---

# MuJoCo reference backend

The Chinese document is the normative source; this page is its official translation.

The output is an `MJCF Bundle`:

```text
scene.xml
meshes/
textures/
native/
build-manifest.json
loss-report.json
conformance-report.json
certificate.json
```

The mapping scope includes static/dynamic rigid bodies, fixed/revolute/prismatic/ball joints, collision, mass and inertia, basic materials, cameras, lights, actuators, and selected sensors. MuJoCo-specific tendon, equality, and plugin features are preserved for round-trip where possible and reported when exporting elsewhere.

L2 uses a locked MuJoCo native loader to compile the model and check resources, units, frames, mass/inertia, and finite numerical values. L3 runs selected rigid-body behaviors such as free fall, rest, ramp, joint limits, drawer motion, or grasp holding.

No frame-by-frame trajectory equivalence with other backends is promised; only declared tests and tolerances are certified.
