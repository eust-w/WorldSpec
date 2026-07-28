---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/product/vision.md
last-verified: 2026-07-28
---

# Product vision

The Chinese document is the normative source; this page is its official translation.

## Positioning

WorldSpec is an embodied-asset platform, not merely a new file format. It provides a canonical semantic model, asset-forging pipeline, cross-backend compilation, diagnostics, and evidence-backed certification.

Its core value is to:

1. bring existing meshes, CAD, robot descriptions, and reconstructions into a unified and traceable asset draft;
2. model visual, collision, mass, semantic geometry, and native payloads separately;
3. perform explicit target-profile transformations and report every approximation, bake, emulation, drop, and unsupported feature;
4. upgrade “generation succeeded” into evidence-backed certification through real loading and behavior tests.

## Target users

- robotics teams converting 3D assets into MuJoCo and web-preview assets at scale;
- simulation engineers who need auditable physics and collision data;
- Real2Sim teams generating asset drafts from images or video;
- asset suppliers publishing traceable bundles.

## Non-goals

- describing every real-world phenomenon;
- claiming frame-by-frame equivalence across physics engines;
- recovering true mass, friction, or hidden structure automatically from one image;
- building a Marketplace, OCI Registry, production web workbench, or complete Task/Benchmark platform in v0.1.

The public brand is undecided; `WorldSpec` is only a working name. Brand and trademark clearance are required before public launch.
