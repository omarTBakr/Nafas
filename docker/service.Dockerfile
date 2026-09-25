# One image recipe for every Python service in the uv workspace. Build from
# the repository root, naming the package and its entrypoint module:
#
#   docker build -f docker/service.Dockerfile \
#     --build-arg PACKAGE=nafas-gateway --build-arg MODULE=nafas_gateway.main .
#
# GPU services are not built from this; each has its own CUDA Dockerfile.

FROM python:3.12-slim-bookworm AS build

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv

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


FROM python:3.12-slim-bookworm

ARG MODULE
ENV PATH="/app/.venv/bin:$PATH" \
    SERVICE_MODULE="$MODULE"

COPY --from=build /app/.venv /app/.venv
# migrations ship with every image, so any service can run them as a one-off job
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
WORKDIR /app

RUN useradd --system --uid 10001 app
USER app

CMD ["sh", "-c", "exec python -m \"$SERVICE_MODULE\""]
