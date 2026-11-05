FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.2 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY velkgram ./velkgram
RUN uv sync --frozen --no-dev

RUN useradd --uid 1000 --home-dir /app velkgram \
    && mkdir -p /app/data \
    && chown velkgram:velkgram /app/data
USER velkgram

CMD ["velkgram", "--help"]
