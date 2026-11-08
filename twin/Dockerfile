# The Twin service. Build context: twin/
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.28 /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_NO_DEV=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project
COPY src/twin ./src/twin
RUN uv sync --locked --no-editable
ENV PATH="/app/.venv/bin:$PATH"
# 8001: the Twin's port in the triplet (root docker-compose.yml, TWIN_URL=http://twin:8001)
EXPOSE 8001
CMD ["uvicorn", "twin.main:app", "--host", "0.0.0.0", "--port", "8001"]
