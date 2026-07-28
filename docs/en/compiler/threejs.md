---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/compiler/threejs.md
last-verified: 2026-07-28
---

# Three.js reference backend

The Chinese document is the normative source; this page is its official translation.

The current reference implementation outputs:

```text
scene.glb
scene-manifest.json
compile-summary.json
build-manifest.json
loss-report.json
worldspec.lock.json
```

An explicit root transform maps canonical +Z Up, +X Forward, right-handed coordinates to glTF/Three.js +Y Up, -Z Forward, and the manifest records that mapping. Stable WorldSpec IDs are retained in glTF node extras. Scale applies only to representations/nodes, never physical Frames.

The current implementation fully emits the diagnostic box and a glTF metallic-roughness material. A single resolved source GLB is preserved byte-for-byte in the Bundle, with `sourceSceneBinding` binding its root to a stable WorldSpec Entity. OBJ-to-GLB conversion, multi-GLB composition, shaders, procedural materials, and neural representations remain incomplete and must enter the LossReport. A real Chromium page using Three.js 0.185.1 has verified reference GLB loading, stable IDs, bounds, camera setup, and screenshot generation.

The Three.js bundle is for preview, inspection, and debugging. Full L2 still requires recording the browser result in a ConformanceReport and issuing a certificate; the current browser smoke test is not an issued L2. Dynamics, contact, or sensor physics are not certified unless a separate physics backend and matching Profile are bound.
