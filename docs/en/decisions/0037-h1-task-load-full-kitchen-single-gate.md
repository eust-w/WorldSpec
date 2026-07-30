---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0037-h1-task-load-full-kitchen-single-gate.md
last-verified: 2026-07-30
---

# ADR-0037: H1 task-load full-kitchen single-run gate

The Chinese document is the normative source; this page is its official translation.

## Context

The ADR-0036 A6-S Job `worldspec-h1-midterm-69xm4` has executed on a real
Drobodata A800. All five walk-settle and five zero-command stand-regression
tests passed, producing `formalTaskLoadSupervisorGate=passed`. The Report,
Controller, and Trace were returned and verified by SHA-256.

This proves only that the 100M Motion Policy and frozen Capture/Stand
Supervisor are compatible under the static A5-CK right-arm load. It does not
prove whole-body task control, drawer contact, mug manipulation, or the full
task.

The historical `fixed_kitchen_full_loop_probe` immediately starts four
additional runs after a passing first run, and its formal Report can pass only
at 5/5. It therefore cannot express the ADR-0036 sequence of one full A5 run
followed by a separate 5/5 decision. It also uses the four-joint Jacobian
controller already known to fail at `reach_handle`.

## Decision

Add the research-only `task_load_fixed_kitchen_single_probe` stage (A6-K1):

1. use exactly the A6-S Motion, Capture, and Stand Policy identities;
2. preserve the A6-S static arm pose and explicit bias load during locomotion
   and initial settling;
3. during the task, reuse the A5-CK whole-body QP, dynamic arm tracking,
   hysteretic task-policy handoff, ergonomic scene, and forward-only base
   recovery contracts; the failed A5-CK evidence is lineage for the controller
   contract only and is never upgraded to passing evidence;
4. execute all 13 ordered phases: stand, reach handle, close, pull, release,
   reach mug, close, lift, insert, release, retract, push drawer, and final hold;
5. keep grasping physical-contact-only and forbid welds, mocap attachments,
   teleportation, or state rewriting;
6. execute exactly one Episode at seed `41`, returning the Report, Controller,
   and step-level Trace whether it passes or fails;
7. a pass creates at most `single_integration_candidate`; 5/5, L3, and public
   release claims remain forbidden;
8. only a passing single-run gate may create a separate fixed-scene 5/5
   Profile. A failure stops the chain and requires a new control decision based
   on the exact phase, termination channels, and contact evidence.

## Evidence boundary

- The passing A6-S result does not substitute for this run.
- Schema, CPU tests, and an OCI build do not substitute for an A800 behavior
  witness.
- The self-authored primitive scene and Robotiq mount remain
  `generated / estimated / internal_only`.
- Even a later 5/5 pass still requires rights, real-kitchen physics evidence,
  and an independent L3 review.
