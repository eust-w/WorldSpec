---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0020-h1-fixed-kitchen-integration.md
last-verified: 2026-07-29
---

# ADR-0020: H1 fixed-kitchen full-loop integration probe

The Chinese document is the normative source; this page is its official translation.

## Context

ADR-0019 produced a passing real-A800 Motion → Capture → Stand three-policy
Supervisor. A4 covers only four-second walk-and-settle behavior and does not
prove manipulation. The user selected A5 to integrate the frozen Supervisor
with a fixed-scene “open drawer → grasp mug → place and release → close
drawer” loop.

## Decision

Add a `fixed_kitchen_full_loop_probe` research stage:

- the legs use only the A4-frozen Motion, Capture, and Stand checkpoints and
  Supervisor;
- the right arm uses damped least-squares position-Jacobian targets executed
  by the existing PD impedance actuators;
- the right Robotiq uses the declared `0` open and `255` close commands;
- the scene uses only self-authored WorldSpec primitive cabinet, sliding
  drawer, handle, support rails, and short-cylinder mug proxy, without copying
  third-party real-kitchen assets;
- grasping relies only on physical contact; hidden welds, mocap attachments,
  teleportation, and state rewriting are forbidden;
- the state order is fixed: stand ready, reach handle, close, pull, release,
  reach mug, close, lift, insert, release, retract, push drawer closed, and
  final hold;
- run one probe first, and only after it passes run four more episodes in the
  same fixed scene; all five must pass to form an `integration_candidate`;
- fail closed on any phase timeout, fall, non-finite value, missing open-drawer
  event, missing final stable/released mug containment, or missing final
  closed-drawer state; and
- do not start 100M training, automatic tuning, or automatic retry.

## Evidence boundary

Even a passing fixed-scene 5/5 A5 result is only
`research_integration_only / internal_only`; it cannot claim L3 because:

- the H1-to-Robotiq mount remains `estimated / unvalidated`;
- the scene is a synthetic primitive proxy rather than rights-cleared real
  kitchen physics evidence; and
- no randomized initialization, physics perturbation, or real-robot
  robustness evidence exists.

Before a real A800 run, this remains Accepted Design. Code, schemas, local
MuJoCo loading, and a built GPU image cannot replace a behavioral witness.
