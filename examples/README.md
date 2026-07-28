# WorldSpec 0.1 examples

Positive WorldDefinition examples:

- `minimal-cube/world.json`
- `hollow-mug/world.json`
- `articulated-drawer/world.json`

`minimal-cube/` also contains valid build/profile/report objects for the public schemas.

`h1-kitchen/` contains the selected, still-estimated right-gripper composition and a
sanitized, real macOS arm64 MuJoCo native-load report. It also contains the
explicit locomotion adapter and its failed behavior report, plus the accepted
A+R target-dynamics training profile and an explicit `blocked / not_executed`
result. It does not contain third-party meshes, new policy weights, GPU-training
evidence, or an H1 task-success witness.

Negative cases live under `negative/` and declare their expected validation layer in `negative/expectations.json`.

`real-kitchen-placeholder/` contains metadata and evidence placeholders only. It intentionally contains no source or reconstructed asset.
