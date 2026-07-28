---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0004-inputs-and-native-payload.md
last-verified: 2026-07-28
---

# ADR-0004: Inputs and native payload

The Chinese document is the normative source; this page is its official translation.

## Decision

v0.1 inputs are GLB, OBJ, URDF, MJCF, STEP, IGES, OpenUSD, single image, multi-view images, and video.

CAD/USD use “profile completeness + Native Payload preservation”: known fields enter editable Core; PMI, GD&T, feature history, proprietary schemas, and unknown fields remain in source blobs by digest.

## Consequences

Accepting input does not mean understanding all semantics. Native payload cannot override Core or disappear silently; unapplied content appears in LossReport for other targets.
