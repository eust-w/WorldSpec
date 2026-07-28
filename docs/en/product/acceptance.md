---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/product/acceptance.md
last-verified: 2026-07-28
---

# Acceptance and certification levels

The Chinese document is the normative source; this page is its official translation.

## Asset levels

| Level | Name | Minimum evidence |
|---|---|---|
| L0 | Parsed | Input parses; provenance and native payload are registered |
| L1 | Canonical Valid | WorldDefinition passes schemas and core invariants |
| L2 | Target Loadable | The target runtime loads the bundle natively and LossReport is complete |
| L3 | Task Validated | The asset passes declared behavior and predicate tests under a Task Profile |

A level is bound to asset digest, TargetProfile, BuildIntent, compiler version, and runtime environment. Any dependency change requires recertification.

## Evidence grades

`measured`, `manufacturer_declared`, `imported`, `reconstructed`, `derived`, `estimated`, `generated`, `default`, and `unknown` describe provenance and authority; they do not replace L0–L3. A generated asset may reach L3 while its mass or friction remains `estimated`.

## v0.1 release acceptance

- All three product loops produce schema-valid, traceable artifacts.
- MuJoCo and Three.js reference compilers reach L2; selected rigid-body tasks reach L3.
- Every non-exact lowering appears in LossReport, using only `exact / converted / approximated / baked / emulated / dropped / unsupported`.
- The conformance corpus covers self-authored synthetic assets and one real-kitchen case with clear rights.
- Bilingual documentation, schemas, examples, report formats, and version policies pass repository checks.
- Performance, memory, cost, load rate, and behavioral deviation are reported from real measurements; unmeasured pass numbers are prohibited.

This repository currently completes the documentation/schema baseline, Rust Validator, platform skeleton, OBJ Doctor, and reference compiler slice, but not full-format compilers, generators, or L2/L3 runtime certification. It does not satisfy product v0.1 acceptance.
