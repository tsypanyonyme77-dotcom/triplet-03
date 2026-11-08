# One image for the Guardian and both mocks; docker-compose picks the command.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY config ./config
COPY mocks ./mocks
COPY scenarios ./scenarios
# 8100 by default; GUARDIAN_PORT or the port of GUARDIAN_URL overrides it (8003 in the triplet root compose).
EXPOSE 8100 8003
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; from guardian.config import Settings; p = Settings().listen_port(8100); urllib.request.urlopen(f'http://localhost:{p}/health', timeout=2)" || exit 1
CMD ["python", "-m", "guardian.main"]
