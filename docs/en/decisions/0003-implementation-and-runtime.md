---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0003-implementation-and-runtime.md
last-verified: 2026-07-28
---

# ADR-0003: Implementation technology and reference runtime

The Chinese document is the normative source; this page is its official translation.

## Decision

The implementation direction is a Rust core with language bindings: Python for generation/scientific computing and TypeScript/WASM for Three.js.

The v0.1 generation reference environment is Linux with an NVIDIA 80 GB GPU, represented by A800/H100. This is a test Profile, not a prohibition on other platforms.

## Consequences

Core semantics are language-independent. Platform/hardware capability belongs in runtime Profiles; untested platforms cannot be claimed as supported. The documentation/schema phase created no product scaffold; the following phase added the first Rust Validator under this ADR.
