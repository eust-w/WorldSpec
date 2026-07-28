# WorldSpec OCI Worker

This package implements the versioned `JobSpec -> JobResult` protocol. It includes:

- isolated `cad` and `openusd` ingestion adapters;
- a locked `trellis2` single-image generation adapter;
- a locked `nerfstudio` multi-view/video generation adapter.

The ingestion adapters execute real `cadquery-ocp` or `usd-core` APIs only when those dependencies are present in a locked worker image. They produce digest-addressed inspection evidence and preserve the source Blob as Native Payload, but do not produce or certify a `WorldDefinition`.

The generation adapters require an exact OCI digest attestation, requested and available CUDA, supported outputs, and locked runtime dependencies. TRELLIS.2 additionally verifies every model-bundle file by SHA-256 and rejects undeclared files or symlinks. Outputs remain `generated` or `estimated`, include a quality report, and must re-enter normal Ingestion and Doctor processing. They do not issue a certificate.

No real A800/H100 generation run is recorded in this repository yet. Current automated tests prove fail-closed profile/container/model gates; they are not GPU execution evidence.

Without a real handler, the worker returns `WORKER_HANDLER_UNAVAILABLE` and exits non-zero. `--mock` is an explicit CI-only digest-preserving echo and is never valid generation, target-load, or certification evidence.

The worker receives an explicit CAS root and resolves every input by SHA-256. Production profiles must bind the built image by OCI digest; the Dockerfile tag is only a build input.

Examples:

```bash
worldspec-worker --adapter cad --job job.json --result result.json --cas-root .worldspec
worldspec-worker --adapter openusd --job job.json --result result.json --cas-root .worldspec
worldspec-worker --adapter trellis2 --job job.json --result result.json --cas-root .worldspec
worldspec-worker --adapter nerfstudio --job job.json --result result.json --cas-root .worldspec
```

## Immutable model-bundle cache

`WORLDSPEC_MODEL_CACHE_ROOT` points to a read-only directory. A model bundle is stored at `<root>/<sha256-hex>/worldspec-model.json`. Its manifest is:

```json
{
  "formatVersion": "0.1.0",
  "backend": "trellis2",
  "digest": "sha256:...",
  "files": [
    {
      "path": "weights/model.bin",
      "digest": "sha256:...",
      "sizeBytes": 123
    }
  ]
}
```

The bundle digest is the SHA-256 of canonical JSON containing `formatVersion`, `backend`, and the path-sorted `files` array. The worker independently verifies that identity, every file digest/size, and the absence of undeclared files.
