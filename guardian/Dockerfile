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
EXPOSE 8100
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://localhost:8100/health', timeout=2)" || exit 1
CMD ["python", "-m", "guardian.main"]
