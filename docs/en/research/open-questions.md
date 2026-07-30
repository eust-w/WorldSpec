---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/research/open-questions.md
last-verified: 2026-07-30
---

# Open technical questions

The Chinese document is the normative source; this page is its official translation.

These require spikes or benchmarks and must not be written as solved in normative prose.

1. **Generation quality**: geometry, PBR, memory, latency, and licensing cost of TRELLIS.2-class backends on target categories.
2. **Video/multi-view**: quality and human minutes from Nerfstudio-class reconstruction to editable mesh/3DGS.
3. **Scale and hidden surfaces**: minimum recapture, marker, or depth evidence required to reduce uncertainty.
4. **Physics inference**: error distributions for mass, inertia, and friction from category/material priors.
5. **Collision selection**: accuracy/performance frontier among primitives, CoACD, and task-aware proxies.
6. **Behavior consistency**: task-specific tolerance across MuJoCo and future Isaac/Genesis profiles.
7. **Predicates**: detection of semantic-truth versus execution-truth divergence.
8. **Cost**: Time-to-SimReady, Human Minutes, GPU Cost, and Certification Pass Rate.
9. **CAD/USD**: verifiable round-trip scope for PMI, GD&T, feature history, and proprietary schemas.
10. **H1 load-aware locomotion**: the formal 100M policy completed training and
    evidence handoff, but zero-command stand planar drift was `0.314–0.324 m`,
    above the `0.20 m` gate. A new experiment must compare using it as a Motion
    Policy under the existing Capture/Stand Supervisor versus adding explicit
    zero-command displacement state and retention reward to a single policy.
    Automatic retry is forbidden before a new ADR.

Every experiment freezes its input corpus, tool version, hardware, metrics, and failure examples.
