FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FASTFUNNEL_HOST=0.0.0.0 \
    FASTFUNNEL_PORT=5005

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY fastfunnel ./fastfunnel
COPY third_party ./third_party
RUN uv sync --frozen --no-dev

EXPOSE 5005
CMD ["uv", "run", "--no-sync", "python", "-m", "fastfunnel.app"]
