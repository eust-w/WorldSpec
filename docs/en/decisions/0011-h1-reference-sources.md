---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0011-h1-reference-sources.md
last-verified: 2026-07-28
---

# ADR-0011: H1 kitchen reference sources

The Chinese document is the normative source; this page is its official translation.

## Decision

The first H1 kitchen L3 case uses:

- MuJoCo Menagerie `unitree_h1` at commit
  `71f066ad0be9cd271f7ed58c030243ef157af9f4`, BSD-3-Clause;
- MuJoCo Menagerie `robotiq_2f85` at the same commit, BSD-2-Clause;
- Unitree RL Gym H1 `motion.pt`, MuJoCo configuration, and reference interface
  at commit `276801e46c5d433564f24658bac64f254b7d2d4b`, BSD-3-Clause.

Exact file, size, tree, and license digests are stored in
[`third_party/h1-kitchen.lock.json`](../../../third_party/h1-kitchen.lock.json).
Meshes and policy weights are not committed to this repository. The secure
fetcher checks out only locked commits, verifies every declared item, and then
marks the cache `verified_not_executed`. A successful download and digest check
does not prove model, policy, or H1 execution.

WorldSpec owns H1/Robotiq composition, namespacing, mount transforms,
ControlProfile, and Derivation while preserving original payloads unchanged.
Assets in the local dirty BiGym worktree are differential references only, not
normative sources or distributable payloads.

## Rationale

Menagerie provides per-directory licenses and derivation notes for both models.
Unitree RL Gym explicitly ships an H1 MuJoCo deployment configuration and a
policy controlling only ten leg joints. Separating source locks from
composition derivations avoids copying ambiguous payloads from a user worktree
and makes later mounting or control changes auditable.

## Open items

- One right Robotiq is selected; its mount transform and authoritative TCP
  still require composition experiments.
- The policy must be executed against the composed H1 dynamics before
  compatibility is claimed.
- Third-party license records do not replace project dual-license, CLA, brand,
  or legal review.
