# syntax=docker/dockerfile:1.7
# LiteLLM v1.105.1 on CPython 3.12 (research R3 packaging finding): the upstream image ships Python 3.13 /
# Unicode 15.1.0, which gcattr alg 1 refuses (R8). Build context: repository root.
FROM ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 AS uv

FROM docker.io/library/python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS build
# Prisma (LiteLLM's virtual-key store) needs Node.js to generate its client.
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv \
    PRISMA_BINARY_CACHE_DIR=/opt/prisma
WORKDIR /src
COPY pyproject.toml uv.lock ./
COPY lib lib
COPY services services
COPY eval/harness/pyproject.toml eval/harness/pyproject.toml
RUN uv sync --frozen --no-dev --no-editable --package gca-capture-litellm \
 && uv pip install --python /app/.venv/bin/python "litellm[proxy]==1.105.1" "prisma>=0.15"
ENV PATH=/app/.venv/bin:$PATH
# Generate the Prisma client for LiteLLM's virtual-key tables at build time (no network needed at run time).
RUN /app/.venv/bin/prisma generate --schema "$(/app/.venv/bin/python -c 'import litellm, os; print(os.path.join(os.path.dirname(litellm.__file__), "proxy", "schema.prisma"))')"

FROM docker.io/library/python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
# LiteLLM runs the Prisma CLI at start-up to apply its schema, which needs Node.js at run time too.
RUN apt-get update && apt-get install -y --no-install-recommends nodejs && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10001 --system --create-home --shell /usr/sbin/nologin gca
COPY --from=build /app/.venv /app/.venv
# The generated Prisma client records the engine path at build time, so build and runtime share one location
# (found on the first kind install: the client looked under /root/.cache, unreadable for uid 10001).
COPY --from=build /opt/prisma /opt/prisma
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/home/gca \
    PRISMA_BINARY_CACHE_DIR=/opt/prisma
USER 10001
EXPOSE 4000
ENTRYPOINT ["litellm"]
CMD ["--config", "/etc/litellm/config.yaml", "--port", "4000"]
