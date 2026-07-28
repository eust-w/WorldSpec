ARG PYTHON_BASE=python:3.12.11-slim-bookworm
FROM ${PYTHON_BASE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 10001 worldspec
WORKDIR /opt/worldspec-worker

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

USER 10001:10001
ENTRYPOINT ["worldspec-worker"]
