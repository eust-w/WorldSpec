# WorldSpec JSON Schema 0.1

All schemas use JSON Schema Draft 2020-12. `world-definition.schema.json` is the canonical world entry point; ingestion, generation, build, runtime, rights, task/control/predicate profiles, task-run evidence, H1 composition profiles and conformance, worker jobs, artifacts, reports, and certificates have separate entry schemas.

`target-profile.schema.json` only describes certified execution targets (`mujoco` and `threejs`). OpenUSD is an ingestion format represented by `ingestion-profile.schema.json`; it is not an Isaac Sim certification claim.

JSON Schema validates structural constraints. Cross-reference existence, ID uniqueness, ownership/frame cycles, evidence authority, lowering coverage, and certificate invalidation require semantic validation.

The `$id` host is a stable namespace placeholder for the working name. Local relative `$ref` values make this repository self-contained.
