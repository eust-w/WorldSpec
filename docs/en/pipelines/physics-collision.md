---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/pipelines/physics-collision.md
last-verified: 2026-07-28
---

# Physics and collision generation

The Chinese document is the normative source; this page is its official translation.

This page defines a candidate pipeline and evidence boundary; it does not claim production-quality algorithms.

## Mass and inertia

The candidate flow combines category/material priors, geometric volume, hollow/solid assumptions, and user evidence. Every result outputs:

- nominal value and interval/distribution;
- intermediate Claims such as density, wall thickness, and center of mass;
- method, version, and assumptions;
- intended task and ValidityDomain.

Closed geometry may support volume integration. Open or thin-shell geometry first needs a mass proxy and cannot use solid volume blindly.

## Collision candidates

Candidates include primitive compounds, convex hulls, CoACD/convex decomposition, task-aware proxies, and accurate collision. Doctor should produce alternatives; BuildIntent selects among accuracy, speed, and target constraints.

## Validation

Triangle error alone is insufficient. Tests include:

- penetration, clearance, and volume coverage;
- contact stability and rest behavior;
- ramp slide/roll, drop, and articulation motion;
- task-specific insertion, containment, or grasping;
- runtime performance and contact counts.

CoACD parameters, runtime, mass error, and physical-prior accuracy are determined by spikes and benchmarks.
