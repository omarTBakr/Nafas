# embeddings: CPU inference image (bge-m3). Build from this directory:
#   docker build -t nafas/embeddings services/embeddings
# CPU by default: the GPU is spent on stt, the dialect-router and tts.

FROM python:3.12-slim-bookworm



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

COPY embeddings ./embeddings
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra model --no-editable

# bake the pinned weights in; the running container never reaches the Hub
RUN python -m embeddings.download
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

RUN useradd --system --uid 10001 app
USER app

EXPOSE 8430
HEALTHCHECK --interval=15s --timeout=3s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8430/health', timeout=2)"

CMD ["python", "-m", "embeddings.main"]
