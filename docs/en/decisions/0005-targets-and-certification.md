---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0005-targets-and-certification.md
last-verified: 2026-07-28
---

# ADR-0005: Targets and certification

The Chinese document is the normative source; this page is its official translation.

## Decision

v0.1 certification backends are MuJoCo and Three.js. OpenUSD is an input/preservation Profile and does not promise Isaac Sim runtime certification.

Automatically generated assets default to at most L2 Target Loadable. They may reach L3 Task Validated after a Task Profile and passing behavior tests, but Generated/Estimated evidence is not promoted.

## Consequences

Certification binds versioned Profiles, bundles, reports, and runtime environments. Three.js without a physics backend certifies only visual/interaction loading. Frame-by-frame equality and lossless cross-backend claims are forbidden.
