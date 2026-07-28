---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/compiler/threejs.md
last-verified: 2026-07-28
---

# Three.js reference backend

The Chinese document is the normative source; this page is its official translation.

Outputs:

```text
scene.glb (or multiple content-addressed GLBs)
scene-manifest.json
textures/
preview/
build-manifest.json
loss-report.json
conformance-report.json
certificate.json
```

The compiler converts canonical +Z Up, +X Forward, right-handed Frames into target scene conventions and records the transform in the manifest. Scale comes only from Representation mapping, never physical Frames.

Materials prefer glTF PBR. Unsupported shaders, procedural materials, or neural representations are marked baked, emulated, or unsupported. Cameras, lights, hierarchy, instances, and animation bindings keep stable WorldSpec ID mapping.

The Three.js bundle is for preview, inspection, and debugging. L2 validates resources, frames/cameras, materials, and visibility. Dynamics, contact, or sensor physics are not certified unless a separate physics backend and matching Profile are bound.
