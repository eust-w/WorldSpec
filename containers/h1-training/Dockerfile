# syntax=docker/dockerfile:1.7
#
# No default is intentional. An evidence-bearing build must supply a Linux
# x86_64 NVIDIA/JAX base by immutable OCI digest:
#   --build-arg TRAINING_BASE_IMAGE=registry/image@sha256:...
ARG TRAINING_BASE_IMAGE
FROM ${TRAINING_BASE_IMAGE}

ARG UV_VERSION=0.8.22

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    JAX_DEFAULT_MATMUL_PRECISION=highest \
    UV_PROJECT_ENVIRONMENT=/opt/worldspec-h1-training/.venv

WORKDIR /opt/worldspec-h1-training

COPY python/worldspec-h1-training/pyproject.toml ./
COPY python/worldspec-h1-training/uv.lock ./
COPY python/worldspec-h1-training/src ./src
COPY python/worldspec-h1-training/README.md ./

RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}" \
    && uv sync --frozen --no-dev --extra runtime

COPY python/worldspec-worker /opt/worldspec-worker
RUN uv pip install \
    --python /opt/worldspec-h1-training/.venv/bin/python \
    /opt/worldspec-worker

ENV PATH="/opt/worldspec-h1-training/.venv/bin:${PATH}"

USER 10001:10001

ENTRYPOINT ["worldspec-worker", "--adapter", "h1-locomotion"]
