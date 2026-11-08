# One image for the Brain and the two stand-in partners: the same code, a different command.
#   docker build -t city-brain/brain:dev .
# The embedding model is baked in, so the first start needs no download. Runs as a non-root user and holds no secret.
FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --extra llm --extra otel
COPY scripts/warm_models.py scripts/warm_models.py
ENV FASTEMBED_CACHE_PATH=/opt/models
RUN uv run --no-sync python scripts/warm_models.py

FROM python:3.12-slim-bookworm
RUN useradd --uid 10001 --create-home brain && mkdir -p /app/state /app/logs && chown -R brain /app
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 FASTEMBED_CACHE_PATH=/opt/models
COPY --from=build --chown=brain /app/.venv /app/.venv
COPY --from=build /opt/models /opt/models
COPY --chown=brain pyproject.toml uv.lock README.md INTERFACE.md ./
COPY --chown=brain src ./src
COPY --chown=brain mocks ./mocks
COPY --chown=brain config ./config
COPY --chown=brain contracts ./contracts
COPY --chown=brain scenarios ./scenarios
COPY --chown=brain docs/baseline ./docs/baseline
COPY --chown=brain deploy ./deploy
USER brain
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=6 CMD python -c "import urllib.request,sys;urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=2)" || exit 1
ENTRYPOINT ["brain"]
CMD ["serve", "--host", "0.0.0.0"]
