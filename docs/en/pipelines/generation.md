---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/pipelines/generation.md
last-verified: 2026-07-28
---

# Image and video generation

The Chinese document is the normative source; this page is its official translation.

Generation is a pluggable Forge adapter, not part of the Core:

```text
GenerationRequest
  -> BackendPlan
  -> RawGenerationArtifacts
  -> GenerationClaims
  -> AssetDraft
```

## Routing

- Single image: the TRELLIS.2 reference adapter outputs a PBR GLB and quality report.
- Multi-view/video: the Nerfstudio 1.1.5 reference adapter outputs a NeRF checkpoint, cameras, 3DGS, and a quality report. v0.1 does not yet claim automatic export of a certifiable mesh.
- Existing geometry: skip generation and enter Ingestion/Doctor.

Backend capability is declared by Profile. Model-private fields never enter Core.

## Implemented execution gates

A real generation Job requires all of the following:

- the running container's declared OCI digest exactly matches `GenerationProfile.containerDigest`;
- the Job explicitly requests a GPU and the Worker detects CUDA;
- backend, version, modality, input cardinality, and requested outputs match the Profile;
- TRELLIS.2 weights come from a read-only content-addressed cache whose manifest, every file SHA-256/size, undeclared files, and symlinks are verified;
- Nerfstudio executables and Python package version match the locked Profile;
- commands execute as argument arrays without a shell and carry a timeout.

An environment variable alone is not remote attestation. It is a local runtime binding injected by the controlled Worker launcher and recorded in the report. Stronger remote attestation belongs to a future Profile.

Generated artifacts enter the CAS with source, model, container, and output digests. Every artifact must re-enter normal Ingestion/Doctor processing. An adapter cannot directly issue a Certificate.

## Evidence boundary

- Visible regions may be `reconstructed` or `generated`; hidden structure carries uncertainty.
- Scale requires a scale marker, camera calibration, CAD, or human measurement; otherwise it remains unknown/estimated.
- Model-created PBR maps remain `generated`.
- Mass, friction, joints, and articulation cannot become measured facts from visual plausibility.

Generated assets are capped at L2 by default. A Task Profile and passing behavior tests may raise the bundle to L3 without raising Claim authority.

## Current evidence status

Adapter code, fail-closed gates, and model-file tamper tests are complete. The repository does not yet contain a real A800/H100 TRELLIS.2 or Nerfstudio run, so GPU execution remains `not_executed`; generation quality, memory, latency, and L2/L3 acceptance are not established.
