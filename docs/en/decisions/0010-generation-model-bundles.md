---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0010-generation-model-bundles.md
last-verified: 2026-07-28
---

# ADR-0010: Content-addressed generation model bundles

The Chinese document is the normative source; this page is its official translation.

## Decision

v0.1 generation workers load models from an external read-only cache. Weights and credentials never enter the repository, Job Manifest, or report. Each model bundle has a canonical manifest. Its bundle digest is the SHA-256 of canonical JSON containing `formatVersion`, `backend`, and path-sorted file records.

The Worker verifies:

- matching bundle digests in the Profile, directory, and manifest;
- every declared file path, SHA-256, and size;
- absence of undeclared files;
- rejection of symlinks and path traversal;
- exactly one selected model bundle for each reference backend Profile.

## Consequences

A directory name or self-declared manifest is not content evidence. OCI, object storage, or offline media may distribute a model bundle, but it must materialize as the same verifiable manifest before entering the Worker read-only cache. Signatures, transparency logs, and remote attestation belong to a future security Profile.
