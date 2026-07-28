---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/implementation/validator.md
last-verified: 2026-07-28
---

# Rust Validator implementation boundary

The Chinese document is the normative source; this page is its official translation.

## Implemented

`worldspec-core` loads local `schemas/0.1`, creates a no-network Schema Registry, and validates JSON with Draft 2020-12 and format checks.

For a schema-valid `WorldDefinition`, it additionally checks:

- duplicate global object IDs;
- World Root, Entity Ownership, and ownership cycles;
- Entity/Frame ownership and root frames;
- missing, multiply-driven, self-linked, unresolved, and cyclic Frame Placement;
- quaternion normalization;
- Component/Representation/Model/Relation references;
- Claim, EvidenceSource, Derivation references and evidence cycles;
- ClockDomain, StateChannel, and InitialState references.

For a schema-valid `LossReport`, it checks entry counts, complete coverage, and optional reporting of non-exact TargetProfile capabilities.

## CLI

```bash
cargo run --quiet -p worldspec-cli -- \
  validate examples/minimal-cube/world.json \
  --schema world-definition.schema.json \
  --schema-dir schemas/0.1 \
  --output json
```

LossReport may include:

```bash
--target-profile examples/minimal-cube/target-profile.json
```

Exit codes:

- `0`: structure and implemented semantic rules pass;
- `1`: invalid document with diagnostics;
- `2`: file, JSON, Schema Catalog, or Validator could not run.

## Not implemented

- every WS-INV-001 through WS-INV-042 rule;
- schema migration, Profile Registry, and extension-namespace governance;
- Parameter/State value typing and unit-dimension solving;
- authority-aware evidence propagation proofs;
- complete BuildIntent-to-LossReport lowering coverage;
- MuJoCo/Three.js compilation, native loading, and L2/L3 certification.

Passing the current Validator proves only a subset of `Canonical Valid` and does not issue a formal L1 certificate.
