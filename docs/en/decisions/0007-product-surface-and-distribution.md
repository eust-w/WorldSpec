---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0007-product-surface-and-distribution.md
last-verified: 2026-07-28
---

# ADR-0007: Product surface and distribution

The Chinese document is the normative source; this page is its official translation.

## Decision

v0.1 uses a CLI and asynchronous API and does not build a production web workbench. The Three.js bundle provides preview and debugging.

Distribution uses local content-addressed manifests, lockfiles, certificates, and reports. OCI Registry and Marketplace are deferred.

## Consequences

Job, Artifact, and Report contracts are stabilized first. Browser UI is not a v0.1 acceptance dependency; local bundles remain inspectable and reproducible offline.
