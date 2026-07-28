---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0002-document-and-schema-binding.md
last-verified: 2026-07-28
---

# ADR-0002: Documentation source and schema binding

The Chinese document is the normative source; this page is its official translation.

## Decision

The repository is the documentation source of truth. All formal documents are fully bilingual; Chinese is normative and English is the official translation.

The v0.1 machine binding is JSON with JSON Schema Draft 2020-12. YAML may become an authoring format only after deterministic conversion into canonical JSON.

## Consequences

CI checks mirrors, metadata, links, JSON, `$ref`, and examples. Chinese and Accepted ADRs govern translation conflicts.
