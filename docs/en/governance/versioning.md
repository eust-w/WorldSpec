---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/governance/versioning.md
last-verified: 2026-07-28
---

# Versioning and governance

The Chinese document is the normative source; this page is its official translation.

## Versioned objects

Schemas, Component/Relation types, Profiles, Predicates, Compilers, Adapters, assets, reports, and certificates are versioned independently. Documentation versions do not replace machine-object versions.

## Compatibility rules

- Patch: documentation or implementation correction without changing valid instances or semantic results.
- Minor: backward-compatible optional capability.
- Major: changes required fields, ID/unit/state meaning, or truth semantics.

Schema `$id` and directory version are immutable; published schemas are never edited in place. A migration produces a new object, Derivation, and MigrationReport.

## Governance process

Use RFC/ADR, Schema Registry, type/capability/Profile/Predicate registries, Conformance Suite, deprecation policy, and migration policy. Extensions use controlled URI namespaces and never hide unregistered Core semantics in generic `properties`.

Certificates bind all digests. When an asset, Profile, tool, backend, or test version changes, the old certificate remains historical but does not apply to the new Build.
