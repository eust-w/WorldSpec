---
status: Official Translation
applies-to: WorldSpec 0.1
normative-language: zh-CN
mirror: ../../zh-CN/decisions/0024-h1-a5ci-corrected-replay.md
last-verified: 2026-07-30
---

# ADR-0024: corrected A5-CI replay with failure-artifact-first handoff

The Chinese document is the normative source; this page is its official
translation.

## Context

Fixed Attempt `a5-ci-20260730-termination-replay-01` executed on one Drobodata
A800, but diagnostic post-processing failed with `KeyError: 'control'` before
the formal Report and artifact handoff. That Attempt proves neither its replay
termination cause nor the original A5-C termination cause.

The user then explicitly authorized continued correction until it passes. This
extends only A5-CI diagnostic correction; it does not automatically authorize
A5, 5/5, 100M, or publishing a failed Controller as a candidate.

## Decision

1. `formalDiagnosticReplayGate=passed` is the pass target for this correction;
   `formalControlGate` remains separately reported and cannot substitute for
   diagnostic correctness.
2. Every correction uses a new source commit, immutable OCI digest, Replay
   Profile, and Attempt ID. Kubernetes automatic retry remains forbidden.
3. Continue correcting only when an implementation defect fails the diagnostic
   gate. Re-run source, evidence, live capacity, and empty-Namespace preflights
   before each replay.
4. Add `artifact_failure_ready` to the entrypoint. On post-processing failure,
   generate a failure index, keep the Pod readable, wait for the Launcher to
   copy any generated Controller, Trace, or Equivalence artifact, then exit
   with the original failure code.
5. The Launcher copies only fixed filenames with size and SHA-256 validation;
   unknown paths, digest mismatch, or Attempt mismatch fail closed.
6. Stop automatic progression and archive evidence once the diagnostic gate
   passes. If `formalControlGate=failed`, use the precise termination cause in
   a new controller-design ADR; do not enter A5 or 100M directly.

## Boundary

- failed Attempt-01 remains immutable and cannot retroactively pass;
- failure-artifact handoff improves diagnosis but does not prove control;
- changing controller, gates, policies, scene, seed, or capacity invalidates
  equivalent-replay status.

## Attempt-02 result

Attempt-02 completed its equivalent replay on a Drobodata A800. Diagnostic
completeness and static semantic equivalence passed. The replay terminated on
`joint_limit` at `right_hip_yaw`; the formal control gate failed and the
Controller remains `non_publishable`.

The Launcher copied the Report, Controller, Trace, and Equivalence artifacts,
then failed while creating the Receipt because `datetime` was not imported.
Because the Receipt and final Schema audit did not complete, Attempt-02 is
treated as a failed formal diagnostic handoff; the `passed` field in the Pod
Report alone is not completion evidence.

The correction replaces the embedded Receipt Python fragment with a standalone,
unit-tested Finalizer that verifies artifact identities before atomic writes.
Attempt-02 remains immutable, and the correction uses a new commit, image, and
Attempt.

## Attempt-03 result

Attempt-03 completed the A800 replay, all four artifact transfers, Receipt
creation, and cross-digest checks. The diagnostic again identified
`right_hip_yaw` `joint_limit`; the formal control gate failed.

The final offline Schema audit found that the Report implementation emitted
`basis/failedChecks/dynamicComparisonIsInformational`, while the frozen Schema
requires `staticSemanticEquivalent`. The formal diagnostic gate therefore
remains failed; the Schema is not relaxed. The corrected shape has been
validated locally against the Report, Equivalence, and Receipt Schemas using
Attempt-03's real artifacts. The next run still uses a new commit, image, and
Attempt.
