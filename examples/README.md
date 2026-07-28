# WorldSpec 0.1 examples

Positive WorldDefinition examples:

- `minimal-cube/world.json`
- `hollow-mug/world.json`
- `articulated-drawer/world.json`

`minimal-cube/` also contains valid build/profile/report objects for the public schemas.

`h1-kitchen/` contains an estimated right-gripper composition candidate and a
sanitized, real macOS arm64 MuJoCo native-load report. It also contains the
explicit locomotion adapter and its failed behavior report. It does not contain
third-party meshes or policy weights and is not an H1 task-success witness.

Negative cases live under `negative/` and declare their expected validation layer in `negative/expectations.json`.

`real-kitchen-placeholder/` contains metadata and evidence placeholders only. It intentionally contains no source or reconstructed asset.
