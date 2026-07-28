---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/product/prd-v0.1.md
last-verified: 2026-07-28
---

# Product requirements v0.1

The Chinese document is the normative source; this page is its official translation.

## Whole-release objective

v0.1 accepts three loops as one release:

1. **Canonical compiler**: compile WorldDefinition into MuJoCo and Three.js bundles.
2. **Existing Asset → SimReady**: ingest mesh/robot/CAD/USD assets and produce AssetDraft, WorldDefinition, reports, and certificates.
3. **Image/Video → AssetDraft**: use pluggable single-image, multi-view, and video backends, then pass their PBR or reconstruction output through the same Doctor and Compiler flow.

All loops share schemas, EvidenceGraph, manifests, LossReport, and certification levels. They must not create private implicit formats.

## Inputs

v0.1 accepts GLB, OBJ, URDF, MJCF, STEP, IGES, OpenUSD, a single image, multi-view images, and video. “Accepted” means an ingestion profile is planned, not that every native feature maps into the Core.

## User flow

```text
ingest/generate
  -> AssetDraft
  -> inspect/resolve
  -> WorldDefinition
  -> validate
  -> compile(target profile)
  -> bundle
  -> certify
```

Unknown native fields and source blobs must be preserved; every degradation must be written to LossReport.

## Functional requirements

- CLI and asynchronous Job API operations: `ingest`, `generate`, `validate`, `compile`, `certify`, `inspect`, and `bundle`.
- Local content-addressed storage for sources, derived resources, manifests, lockfiles, reports, and certificates.
- MuJoCo compilation produces a natively loadable MJCF bundle.
- Three.js compilation produces GLB, scene manifest, and preview/debug bundle.
- Pluggable generation backends, with TRELLIS.2 as the reference single-image adapter and a Nerfstudio-class adapter for multi-view/video.
- CAD/OpenUSD use profile completeness and native-payload preservation; unknown fields are never silently discarded.
- Generated assets are capped at L2 by default; L3 requires a Task Profile and passing behavior tests.

## Non-functional requirements

- Linux with an NVIDIA 80 GB GPU (reference A800/H100) is the v0.1 reference generation environment.
- Identical input, tools, profile, and lockfile should produce identical content digests; cross-hardware claims are behavioral or statistical only.
- Reports are machine-readable and reference immutable digests and exact tool versions.
- Untrusted assets are treated as data. Executable plugins are isolated and disabled by default.
- Performance, memory, cost, and CoACD parameters must come from benchmarks or spikes, not invented requirements.

## Product surface

v0.1 does not include a production web workbench. The Three.js bundle is for preview, inspection, and debugging and is not automatically a physics-evaluation backend.
