# One image recipe for every Python service in the uv workspace. Build from
# the repository root, naming the package and its entrypoint module:
#
#   docker build -f docker/service.Dockerfile \
#     --build-arg PACKAGE=nafas-gateway --build-arg MODULE=nafas_gateway.main .
#
# GPU services are not built from this; each has its own CUDA Dockerfile.

# pinned by digest: a rebuild of the same commit gets the same base
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e

FROM ghcr.io/astral-sh/uv:0.11@sha256:77280f2f771df71f90786c314fe1bbc1e023feac652969bbf139c280babf2eb7 AS uv

FROM ${PYTHON_IMAGE} AS build

COPY --from=uv /uv /bin/uv

ARG PACKAGE
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY . .

# only this service and what it depends on (nafas-core), installed as real
# packages rather than editable links to /app, so the runtime stage needs
# nothing but the virtualenv
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package "$PACKAGE" --no-editable


FROM ${PYTHON_IMAGE}

# system tools one service needs and the others do not (clinical-records: OCR)
ARG SYSTEM_PACKAGES=""
RUN if [ -n "$SYSTEM_PACKAGES" ]; then \
        apt-get update && apt-get install -y --no-install-recommends $SYSTEM_PACKAGES && rm -rf /var/lib/apt/lists/*; \
    fi

ARG MODULE
# the commit, reported on /health; `make images` passes `git rev-parse --short HEAD`
ARG GIT_SHA=""
ENV PATH="/app/.venv/bin:$PATH" \
    SERVICE_MODULE="$MODULE" \
    GIT_SHA="$GIT_SHA"

COPY --from=build /app/.venv /app/.venv
# migrations ship with every image, so any service can run them as a one-off job
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
WORKDIR /app

RUN useradd --system --uid 10001 app
USER app

CMD ["sh", "-c", "exec python -m \"$SERVICE_MODULE\""]
