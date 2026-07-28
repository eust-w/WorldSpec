---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/architecture/evidence-and-uncertainty.md
last-verified: 2026-07-28
---

# Evidence and uncertainty

The Chinese document is the normative source; this page is its official translation.

EvidenceGraph contains Claims, EvidenceSources, and Derivations. Every high-impact property affecting mass, inertia, collision, joints, scale, or certification must trace to a Claim or an explicit Default Policy.

## Claim

A Claim identifies a target field, nominal value, unit, interval/distribution, evidence status, and validity domain. Status is one of:

`measured / manufacturer_declared / imported / reconstructed / derived / estimated / generated / default / unknown`

Later stages must never silently promote `generated`, `estimated`, or `default` to `measured`.

## EvidenceSource and Derivation

EvidenceSource records source digest, rights status, acquisition method, and time. Derivation records algorithm, version, input claims, output claims, and assumptions. EvidenceGraph is a DAG.

## Uncertainty propagation

- Reducing an interval/distribution to a nominal value declares a `nominal / conservative / optimistic / sampled / measured-only` policy.
- Derived results retain their inputs, assumptions, and method version.
- Unsupported propagation is marked `unpropagated`; uncertainty is never discarded silently.
- L2/L3 certification does not change a generated asset’s evidence status.

Evidence grade explains why a value is believed. Certification level explains what passed for a target and test profile. They remain separate.
