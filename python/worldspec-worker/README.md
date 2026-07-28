# WorldSpec OCI Worker

This package implements the versioned `JobSpec -> JobResult` protocol. It includes optional isolated `cad` and `openusd` ingestion adapters. They execute real `cadquery-ocp` or `usd-core` APIs only when those dependencies are present in a locked worker image; otherwise they fail with `WORKER_DEPENDENCY_UNAVAILABLE` and `executionEvidence: not_executed`.

The current adapters produce a digest-addressed ingestion inspection and preserve the source Blob as Native Payload evidence. They do not produce or certify a `WorldDefinition`. GPU, Doctor, and compiler handlers are not included yet.

Without a real handler, the worker returns `WORKER_HANDLER_UNAVAILABLE` and exits non-zero. `--mock` is an explicit CI-only digest-preserving echo and is never valid generation, target-load, or certification evidence.

The worker receives an explicit CAS root and resolves every input by SHA-256. Production profiles must bind the built image by OCI digest; the Dockerfile tag is only a build input.

Examples:

```bash
worldspec-worker --adapter cad --job job.json --result result.json --cas-root .worldspec
worldspec-worker --adapter openusd --job job.json --result result.json --cas-root .worldspec
```
