---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/architecture/time-state-events.md
last-verified: 2026-07-28
---

# Time, state, and events

The Chinese document is the normative source; this page is its official translation.

## Permanent separation

- **Parameter**: mass, inertia, limits, intrinsics, and material parameters immutable within a WorldDefinition revision.
- **InitialState**: the Episode starting point, not a permanent asset parameter.
- **StateChannelDescriptor**: the Subject, Property, unit, ClockDomain, and interpolation semantics of a state.
- **StateStream**: time-sampled values in RuntimeRecord.
- **EventLog**: discrete events and causal references.

## Time model

Simulation, control, sensor, render, and wall-clock domains are distinct. Every StateStream/Event declares its ClockDomain; cross-domain alignment declares synchronization, interpolation, and latency policies.

Timestamps are non-decreasing within a Stream/Epoch. Reset starts a new Epoch. A Snapshot binds to a WorldDefinition digest and must not promise bitwise restoration of backend contact state that the target cannot serialize.

## Authority

A world pose derived from the Frame Graph cannot be stored as a second authoritative state. Each driven Frame has one authoritative driver per Build. Runtime writes never mutate static Parameters; parameter changes use an override or a new revision.
