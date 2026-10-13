<div align="center">
  <img src="docs/readme/hero.svg" alt="WorldSpec — workflow overview" width="100%">
  <h1>WorldSpec</h1>
  <p><strong>Traceable semantics, explicit conversion loss and verifiable simulation artifacts.</strong></p>
  <p><a href="https://github.com/eust-w/WorldSpec/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/eust-w/WorldSpec/ci.yml?branch=feature%2Fworldspec-v0.1&amp;style=flat-square&amp;label=CI"></a>
  <img alt="Version: 0.1" src="https://img.shields.io/badge/Version-0.1-467bc7?style=flat-square">
  <img alt="Core: Rust + JSON Schema" src="https://img.shields.io/badge/Core-Rust%20%2B%20JSON%20Schema-547ac4?style=flat-square">
  <img alt="License: Pending final texts" src="https://img.shields.io/badge/License-Pending%20final%20texts-b57d35?style=flat-square"></p>
  <p>
    <a href="#overview">Overview</a> ·
    <a href="#quick-start">Quick start</a> ·
    <a href="#workflow">Workflow</a> ·
    <a href="#validation">Validation</a> ·
    <a href="#documentation">Documentation</a>
  </p>
  <p><a href="README.en.md">English</a> · <a href="README.md">简体中文</a></p>
</div>

---

<a id="overview"></a>
## Know what a world can support

**WorldSpec** defines a semantic and evidence model for embodied assets, together with a compilation layer across simulators. It connects source provenance, world definitions, target conditions and conversion loss in a shared contract that can be inspected and validated.

| Describe a world | Compile for a target | Inspect the evidence |
| :--- | :--- | :--- |
| Schemas, provenance and object relationships | Target profiles, bundles and loss reports | Structural checks, invariants, digests and conformance reports |

> [!IMPORTANT]
> This is a v0.1 development baseline. Schemas and validation tooling are implemented, but whole-product acceptance is incomplete. A result for one local profile does not establish support for every platform or a complete robot task.

<a id="quick-start"></a>
## Quick start: validate a minimal world

Requires **Rust 1.89+**. This path does not require a GPU or training weights.

```bash
git clone https://github.com/eust-w/WorldSpec.git
cd WorldSpec
cargo run --quiet -p worldspec-cli -- \
  validate examples/minimal-cube/world.json --output json
```

For the documentation/schema baseline, use Python; CI uses Python 3.12:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python scripts/validate_baseline.py
```

Start with the [minimal example](examples/minimal-cube/), then inspect the [schemas](schemas/0.1/) and [validator boundaries](docs/en/implementation/validator.md).

<a id="workflow"></a>
## Connect the asset chain to the evidence chain

```text
SourceBundle → AssetDraft → WorldDefinition
                                  │
                    TargetProfile + BuildIntent
                                  ▼
                 ArtifactBundle + LossReport + BuildManifest
                                  │
                                  ▼
                     ConformanceReport + Certificate
```

| Object | Question it answers |
| :--- | :--- |
| `SourceBundle` | Where did the inputs come from, and what provenance accompanies them? |
| `WorldDefinition` | Which objects, properties and relationships define the world? |
| `TargetProfile` / `BuildIntent` | Which runtime and compilation objective are being targeted? |
| `ArtifactBundle` / `LossReport` | What was produced, preserved or lost? |
| `ConformanceReport` / `Certificate` | Which checks hold under which conditions? |

| Layer | Implementation |
| :--- | :--- |
| Specification | [JSON Schema](schemas/0.1/) and [examples](examples/) |
| Validation and digests | [Core](crates/worldspec-core/) and [CLI](crates/worldspec-cli/) |
| Compilation and certificates | [Compiler](crates/worldspec-compiler/) and [Cert](crates/worldspec-cert/) |
| Artifacts and execution | [CAS](crates/worldspec-cas/) and [Forge](crates/worldspec-forge/) |
| API and preview | [Loopback server](crates/worldspec-server/) and [Three.js](web/threejs-preview/) |

<a id="validation"></a>
## Match the claim to the check

```bash
cargo test --workspace
python scripts/validate_baseline.py
python scripts/validate_compilers.py
python scripts/validate_robot_ingestion.py
```

Runtime checks require their corresponding dependencies:

```bash
python scripts/validate_l2_certification.py
python scripts/validate_l2_threejs.py
```

| Area | Current boundary |
| :--- | :--- |
| Schema / Validator | Draft 2020-12 plus registered cross-object invariants |
| MuJoCo / Three.js | Reference compilation and local runtime evidence, bound to the actual OS, architecture and profile |
| L2 certificates | Local unsigned certificates and tamper-rejection checks, not independent third-party certification |
| OpenUSD / Isaac Sim | Native-payload preservation does not establish runtime certification |
| H1 policies | Research artifacts remain `non_publishable`; complete kitchen-task success is not claimed |
| HTTP service | Defaults to `127.0.0.1:8090`; no account, multi-tenant or remote-service security boundary |

<details>
<summary><strong>Retained research checkpoint</strong></summary>

> Repository status: this repository contains v0.1 documentation, 45 JSON Schemas, examples, Rust Core/Validator, canonical digests, a file CAS, SQLite WAL job index, optional Ed25519 certificate signing, CLI, and a loopback asynchronous API. MuJoCo/Three.js reference compilation, local macOS arm64 L2 evidence, immutable L3 TaskRun/RuntimeRecord assessment, the Reference Predicate Engine, fail-closed generation workers, selected ingestion/Doctor slices, and deterministic locked-source H1/right-Robotiq composition are implemented. The H1 composition has passed local native loading, but its mount remains estimated. The locked Unitree gait policy passes interface inference but fails the four-second behavior check on the Menagerie whole-body model. The user selected the A+R target-dynamics retraining route and confirmed MuJoCo Playground v0.2.0, MuJoCo/MJX, Warp, and Brax JAX PPO. The source lock, target-bundle adapter, profile, `train` Job, and fail-closed Worker gates exist; the derived training model passes a local MuJoCo 3.6.0 native load. An isolated A800 compatibility spike and one 32,768-requested-step, 256-environment A800 PPO research smoke for the prior capacity Profile executed successfully; that smoke is explicitly `non_publishable` and saved no checkpoint. After reviewing the official MJX capacity semantics, the current Profile now scales `naconmax/naccdmax` per environment and keeps `njmax` per world. A new digest-pinned image built from commit `101aff7`, its A800 one-step, and the exact 8,192-environment capacity-scale preflight all pass for the current Profile with finite batched state and zero capacity overflows. A capacity-corrected 32,768-requested-step, 256-environment A800 PPO research smoke also passes with finite training/inference values and zero capacity overflows; however, its mean evaluation episode length is only about 87.34 steps, it remains `non_publishable`, and it saved no checkpoint, so it does not establish policy quality. The separate `stand-v2.1` calibration has now executed 4,194,304 requested steps on a real A800, reached mean episode length 500, improved 4.02 times over `stand-v1`, passed all five deterministic stand checks, and retrieved its internal checkpoint with exact size and digest verification. This remains `research_calibration / non_publishable` evidence and only permits the next walking-curriculum experiment. Linux x86_64 reference L2, real A800/H100 generation, canonical H1 training, full CAD/USD native execution, and the H1 kitchen 5/5 L3 witness remain incomplete, so product v0.1 is not accepted as a whole.

</details>

<a id="documentation"></a>
## Documentation

| Guide | Focus |
| :--- | :--- |
| [English docs](docs/en/index.md) · [中文文档](docs/zh-CN/index.md) | Chinese is the specification source of truth |
| [Product requirements](docs/en/product/prd-v0.1.md) | v0.1 scope |
| [Architecture](docs/en/architecture/overview.md) | Object model and boundaries |
| [Decision register](docs/en/decision-register.md) | Accepted design and experiment decisions |
| [OpenAPI](openapi/worldspec-v1.yaml) | Service contract |
| [License governance](docs/en/governance/licensing.md) | Open-core and contribution policy |

## License status

The accepted direction is **AGPL-3.0 open core + commercial licensing + a CLA**. [LICENSES/README.md](LICENSES/README.md) states that the final license and CLA texts are not yet part of the baseline. Public repository visibility does not finalize those grants. Code, models, datasets and derived assets need their respective terms.
