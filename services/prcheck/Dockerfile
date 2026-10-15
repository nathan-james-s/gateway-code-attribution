# syntax=docker/dockerfile:1.7
# Build context: repository root (scripts/build-images.sh). eval/ is never copied (Constitution II, T111).
FROM ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 AS uv

FROM docker.io/library/python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS build
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY pyproject.toml uv.lock ./
COPY lib lib
COPY services services
COPY eval/harness/pyproject.toml eval/harness/pyproject.toml
RUN uv sync --frozen --no-dev --no-editable --package gca-prcheck

FROM docker.io/library/python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
RUN useradd --uid 10001 --system --no-create-home --shell /usr/sbin/nologin gca
COPY --from=build /app/.venv /app/.venv

ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001
ENTRYPOINT ["uvicorn", "gca_prcheck.asgi:app", "--host", "0.0.0.0", "--port", "8080"]
