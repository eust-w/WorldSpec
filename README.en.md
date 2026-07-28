# WorldSpec (working name)

WorldSpec is a canonical semantic model, evidence model, and cross-simulator compilation IR for embodied assets. It aims to turn existing assets or image/video generation results into traceable, verifiable, and loss-transparent SimReady assets.

> Repository status: this repository contains v0.1 documentation, 32 JSON Schemas, examples, Rust Core/Validator, canonical digests, a file CAS, SQLite WAL job index, optional Ed25519 certificate signing, CLI, and a loopback asynchronous API. MuJoCo/Three.js reference compilation, local macOS arm64 L2 evidence, immutable L3 TaskRun/RuntimeRecord assessment, the Reference Predicate Engine, fail-closed generation workers, selected ingestion/Doctor slices, and deterministic locked-source H1/Robotiq composition are implemented. The H1 composition has passed local native loading, but its mount remains estimated. Linux x86_64 reference L2, real A800/H100 generation, full CAD/USD native execution, and the H1 kitchen 5/5 L3 witness remain incomplete, so product v0.1 is not accepted as a whole.

## Entry points

- [中文文档（规范真源）](docs/zh-CN/index.md)
- [English documentation (official translation)](docs/en/index.md)
- [Product requirements v0.1](docs/en/product/prd-v0.1.md)
- [Architecture overview](docs/en/architecture/overview.md)
- [Decision register](docs/en/decision-register.md)
- [Validator implementation boundary](docs/en/implementation/validator.md)
- [JSON Schema 0.1](schemas/0.1/)
- [OpenAPI v1](openapi/worldspec-v1.yaml)
- [Minimal examples](examples/)

## Baseline scope

```text
SourceBundle -> AssetDraft -> WorldDefinition
WorldDefinition + TargetProfile + BuildIntent
    -> ArtifactBundle + LossReport + BuildManifest
    -> ConformanceReport + Certificate
```

v0.1 plans to certify MuJoCo and Three.js. OpenUSD is an input and native-payload preservation profile only; it does not imply Isaac Sim runtime certification.

## Validation

```bash
python3 scripts/validate_baseline.py
git diff --check
```

The utility checks JSON/Schema documents, `$ref` integrity, positive and negative cases, bilingual mirrors, document metadata, and local links. It is not the product runtime validator.

Rust Validator:

```bash
cargo run --quiet -p worldspec-cli -- \
  validate examples/minimal-cube/world.json --output json

cargo test --workspace
```

`worldspec validate` runs Draft 2020-12 schema validation and registered cross-object invariants. `worldspec-server` listens only on `127.0.0.1:8090` by default; the API does not yet provide accounts, multi-tenancy, or a remote-network security boundary.

## Licensing status

The accepted product strategy is `AGPL-3.0 + commercial license + CLA`. The commercial license, CLA, and complete legal files still require legal review; repository notes are not legal advice. See [licensing governance](docs/en/governance/licensing.md).
