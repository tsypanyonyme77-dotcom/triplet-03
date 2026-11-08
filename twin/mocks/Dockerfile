# A mock partner with its console. Build context: twin/. Build arg MOCK: brain or guardian.
FROM node:22-slim AS console
WORKDIR /ui
COPY mocks/ui/package.json mocks/ui/package-lock.json ./
RUN npm ci
COPY mocks/ui ./
RUN npm run build

FROM python:3.12-slim
ARG MOCK
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY mocks/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY mocks/${MOCK}/ ./
COPY --from=console /ui/dist ./ui
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
