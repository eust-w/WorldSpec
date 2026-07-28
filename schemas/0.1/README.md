# WorldSpec JSON Schema 0.1

All schemas use JSON Schema Draft 2020-12. `world-definition.schema.json` is the canonical world entry point; build and report objects have separate entry schemas.

JSON Schema validates structural constraints. Cross-reference existence, ID uniqueness, ownership/frame cycles, evidence authority, lowering coverage, and certificate invalidation require semantic validation.

The `$id` host is a stable namespace placeholder for the working name. Local relative `$ref` values make this repository self-contained.
