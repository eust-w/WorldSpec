---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/interfaces/reports.md
last-verified: 2026-07-28
---

# Reports and public artifacts

The Chinese document is the normative source; this page is its official translation.

## LossReport

Records source semantics, target capability, lowering status, rationale, consequence, and diagnostics for each item. Status is exactly one of:

`exact / converted / approximated / baked / emulated / dropped / unsupported`

An empty report means every item is exact only when a coverage check proves it; the report itself is never omitted.

## BuildManifest

Locks digests for WorldDefinition, EvidenceGraph, TargetProfile, BuildIntent, Compiler, BackendCalibration, Model/Representation selections, source resources, and output artifacts.

## ConformanceReport

Records test ID/version, runner digest, TargetProfile digest, target, actual environment, tested artifacts, result, metrics, tolerances, and evidence artifacts. `executionEvidence` is explicitly `executed` or `not_executed`; the latter cannot carry passing runtime tests. `not_run` and `unknown` never count as pass.

Test entries deterministically derive summary counts and `overall`; callers cannot self-declare them. L2 requires actual OS, architecture, and runtime version to exactly match the TargetProfile.

## Certificate

Summarizes L0–L3, applicable Profile, referenced digests, issuer, and validity without copying test detail. Before L2 issuance, WorldDefinition, TargetProfile, BuildManifest, LossReport, ConformanceReport, and every Bundle artifact digest/size are verified. A change to any input, tool, Profile, or test rule invalidates it.

Reports are machine-readable, immutable, and distinguish design claims from real execution evidence.
