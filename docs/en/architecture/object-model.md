---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/architecture/object-model.md
last-verified: 2026-07-28
---

# Core object model

The Chinese document is the normative source; this page is its official translation.

WorldDefinition is a canonical object store with multiple graphs, not a single scene tree.

## Core objects

- **Entity**: stable identity, ownership, and lifecycle; it is not a Mesh or RigidBody.
- **Frame**: a right-handed, metric SE(3) spatial reference only. Scale is handled or baked in Representation.
- **Component**: a versioned capability or model owned by an Entity, such as rigid body, collider, or camera.
- **Relation**: a connection among Frames, Entities, Components, or Relations, such as fixed, joint, constraint, or transmission.
- **Representation**: a digital representation of a Subject for visual, collision, mass, semantic geometry, and related roles.
- **Model**: selects Components and Representations under declared Purpose, Assumptions, and ValidityDomain.

## Three structures remain separate

1. **Ownership Tree**: versioning, deletion, namespace, and lifecycle; acyclic.
2. **Frame Placement Graph**: authoritative spatial parentage; each active non-root Frame has exactly one driver and the graph is acyclic.
3. **General Relation Graph**: joints, constraints, transmissions, and semantic relations; cycles are allowed but it cannot become a second pose authority.

## Key invariants

- One WorldDefinition has exactly one World Root Entity and Root Frame.
- Every spatial Entity has one root frame; every Frame belongs to one Entity.
- IDs are globally unique and never derived from labels, array positions, or backend names.
- Visual, collision, mass, and semantic-geometry roles are explicit and separate.
- Each active Model Family deterministically selects one Model.
- Components and Relations declare type URIs and schema versions.
- Schemas enforce structure; the semantic Validator enforces references, uniqueness, graph cycles, and evidence coverage.
