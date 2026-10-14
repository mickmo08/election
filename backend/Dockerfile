# syntax=docker/dockerfile:1.7
FROM python:3.13-slim AS build
WORKDIR /src
RUN pip install --no-cache-dir uv==0.5.11
COPY pyproject.toml ./
COPY app ./app
RUN uv pip install --system --no-cache --target /deps .

FROM python:3.13-slim
ARG ELECTION_APP_VERSION=dev
ENV ELECTION_APP_VERSION=${ELECTION_APP_VERSION} PATH=/deps/bin:$PATH PYTHONPATH=/deps:/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10001 --create-home app \
 && mkdir -p /data/raw && chown -R 10001:10001 /data
COPY --from=build /deps /deps
WORKDIR /app
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
# Same image runs: api (default), worker (`python -m app.cli worker`), scheduler, and migrations (`alembic upgrade head`).
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]
