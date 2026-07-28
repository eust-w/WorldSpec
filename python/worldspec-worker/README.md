# WorldSpec OCI Worker

This package implements the versioned `JobSpec -> JobResult` protocol. It does not include GPU, CAD, USD, Doctor, or compiler handlers yet.

Without a real handler, the worker returns `WORKER_HANDLER_UNAVAILABLE` and exits non-zero. `--mock` is an explicit CI-only digest-preserving echo and is never valid generation, target-load, or certification evidence.

The worker receives an explicit CAS root and resolves every input by SHA-256. Production profiles must bind the built image by OCI digest; the Dockerfile tag is only a build input.
