---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/pipelines/ingestion.md
last-verified: 2026-07-28
---

# Asset ingestion

The Chinese document is the normative source; this page is its official translation.

Every input first becomes a `SourceBundle` containing file digests, format detection, rights declaration, scan report, unit/frame hints, and Native Payload index. It then becomes an `AssetDraft`, never a certified WorldDefinition directly.

## Profiles

| Profile | Inputs | Main actions | Typical unresolved items |
|---|---|---|---|
| Mesh | GLB, OBJ | nodes, meshes, textures, materials, unit inference | scale, normals, hollow/solid |
| Robot | URDF, MJCF | links/bodies, joints, inertia, meshes, native extensions | controllers, transmissions, loops |
| CAD | STEP, IGES | assembly, B-Rep, tessellation, PMI payload | units, feature history, GD&T |
| OpenUSD | USD family | prims, materials, physics schemas, variants payload | proprietary schemas, plugins |

## Stages

```text
quarantine -> fingerprint -> parse -> normalize draft
-> extract resources -> map canonical fields
-> preserve native payload -> diagnose -> AssetDraft
```

Units, up/forward axes, handedness, and quaternion order are explicit. Inferred values are Claims, never source declarations. Source files are read-only; every repair creates a new blob and Derivation.

“Input accepted” and “input fully understood” are reported separately.

## Current implementation evidence

The Rust Forge implements pre-parser source scanning: size limits, a ZIP/archive isolation gate, XML external-entity rejection, and remote/path-traversal reference rejection. ROS `package://` is retained only as a controlled package-local reference. The OBJ Doctor implements vertex, face, bounds, degenerate-face, and malformed-line diagnostics plus an immutable “remove degenerate faces” repair. Source and repaired resources are stored separately in CAS, with a Derivation binding both digests.

The GLB Doctor validates v2 containers, declared lengths, JSON chunks, and node/mesh/material tables. The URDF/MJCF Doctor extracts links/bodies, single-parent joint trees, axes, limits, and local poses while rejecting duplicate names, multiply-parented links, missing endpoints, non-positive mass, and non-positive-definite inertia. A safe single-file robot description produces a schema-valid `candidateWorldDefinition`: a logical Robot remains the ownership parent while kinematics come exclusively from the Frame Placement Graph; the source XML is also preserved as a Native Payload.

The robot candidate proves only that source structure can be mapped canonically. Mesh/package resolution, actuators, sensors, transmissions, mass/inertia, and collision remain blocking items; compiler diagnostic boxes and MuJoCo default dynamics are not L2 evidence. CAD, OpenUSD, and archive semantic ingestion remain incomplete. Archived formats such as USDZ are rejected until the bounded expansion worker exists.

The Python OCI Worker now exposes optional `cad` and `openusd` real-API adapter skeletons. The former calls OpenCascade for STEP/IGES roots, bounds, and topology counts; the latter calls `usd-core` for Stage, Prim, Up Axis, and unit inspection. Each adapter emits only a content-addressed `ingestion_inspection`, preserves the source Blob, and blocks canonical mapping; it does not issue a WorldDefinition. Neither native dependency is installed on the current host. Tests prove the explicit `WORKER_DEPENDENCY_UNAVAILABLE / not_executed` failure path, not CAD/USD runtime execution.
