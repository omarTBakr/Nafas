# stt: CUDA inference image. Build from this directory:
#   docker build -t nafas/stt services/stt
# Runs on CPU too when no GPU is passed in, much slower.

FROM python:3.12-slim-bookworm

# ffmpeg decodes whatever the browser recorded (webm/opus, ogg, mp4...)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra model --no-install-project

COPY stt ./stt
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra model --no-editable

# bake the pinned weights in; the running container never reaches the Hub
RUN python -m stt.download
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

RUN useradd --system --uid 10001 app
USER app

EXPOSE 8420
HEALTHCHECK --interval=15s --timeout=3s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8420/health', timeout=2)"

CMD ["python", "-m", "stt.main"]
