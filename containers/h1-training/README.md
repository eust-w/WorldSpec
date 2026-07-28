# H1 training image candidate

This recipe packages the locked `worldspec_h1_training` backend together with
the generic OCI worker. It intentionally has no default base image.

An evidence-bearing build must provide an NVIDIA/JAX-compatible Linux x86_64
base by immutable digest:

```bash
docker build \
  --file containers/h1-training/Dockerfile \
  --build-arg TRAINING_BASE_IMAGE=registry.example/image@sha256:... \
  --tag worldspec-h1-training:candidate \
  .
```

Building this recipe does not change `runtime.status` to `locked`. That requires
recording the resulting OCI digest and package-lock digest in the training
profile, then passing the real GPU runtime preflight. No such image or GPU
evidence is committed yet.
