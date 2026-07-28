---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0006-generation-and-corpus.md
last-verified: 2026-07-28
---

# ADR-0006: Generation adapters and corpus

The Chinese document is the normative source; this page is its official translation.

## Decision

Generation backends are pluggable. [TRELLIS.2](https://github.com/microsoft/TRELLIS.2) is the reference single-image backend because it can output PBR GLB and uses MIT licensing; multi-view/video uses a [Nerfstudio](https://github.com/nerfstudio-project/nerfstudio)-class reconstruction adapter.

The conformance corpus contains self-authored synthetic assets and one rights-cleared end-to-end real-kitchen case.

## Consequences

Model, weights, and data licenses are locked separately. The kitchen has only manifest/evidence placeholders until rights are confirmed. Performance, memory, and processing cost are measured in benchmarks, never invented.
