# syntax=docker/dockerfile:1.7
#
# No default is intentional. An evidence-bearing build must supply a Linux
# x86_64 NVIDIA/JAX base by immutable OCI digest:
#   --build-arg TRAINING_BASE_IMAGE=registry/image@sha256:...
ARG TRAINING_BASE_IMAGE
FROM ${TRAINING_BASE_IMAGE}

ARG UV_VERSION=0.8.22
ARG PYTHON_VERSION=3.12.11
ARG WORLDSPEC_SOURCE_COMMIT
ARG WORLDSPEC_PACKAGE_LOCK_DIGEST

# The pinned base image runs as UID 10001. Build-time package installation and
# ownership setup are explicit root-only steps; the final runtime switches back
# to the fixed non-root UID below.
USER 0:0

LABEL org.opencontainers.image.source="https://github.com/eust-w/WorldSpec" \
      org.opencontainers.image.revision="${WORLDSPEC_SOURCE_COMMIT}" \
      dev.worldspec.h1.package-lock="${WORLDSPEC_PACKAGE_LOCK_DIGEST}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    JAX_DEFAULT_MATMUL_PRECISION=highest \
    UV_PYTHON_INSTALL_DIR=/opt/worldspec-h1-training/.python \
    UV_PROJECT_ENVIRONMENT=/opt/worldspec-h1-training/.venv

WORKDIR /opt/worldspec-h1-training

COPY python/worldspec-h1-training/pyproject.toml ./
COPY python/worldspec-h1-training/uv.lock ./
COPY python/worldspec-h1-training/src ./src
COPY python/worldspec-h1-training/README.md ./

RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}" \
    && uv python install "${PYTHON_VERSION}" \
    && uv sync --frozen --no-dev --extra runtime --python "${PYTHON_VERSION}"

COPY python/worldspec-worker /opt/worldspec-worker
RUN uv pip install \
    --python /opt/worldspec-h1-training/.venv/bin/python \
    --no-deps \
    /opt/worldspec-worker \
    && /opt/worldspec-h1-training/.venv/bin/python -c \
      'import importlib.metadata as m; assert m.version("jsonschema") == "4.26.0"' \
    && mkdir -p /home/worldspec /workspace/input /workspace/output \
    && chown -R 10001:10001 /home/worldspec /workspace

ENV HOME=/home/worldspec \
    PATH="/opt/worldspec-h1-training/.venv/bin:${PATH}"

USER 10001:10001

ENTRYPOINT ["worldspec-worker", "--adapter", "h1-locomotion"]
