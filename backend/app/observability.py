"""Structured JSON logging, Prometheus metrics and request correlation."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
import uuid
from datetime import UTC, datetime

from prometheus_client import Counter, Gauge, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
tenant_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("tenant_id", default=None)

HTTP_REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP latency", ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
JOBS_PROCESSED = Counter("jobs_processed_total", "Jobs processed", ["kind", "outcome"])
JOBS_DEAD = Gauge("jobs_dead_letter", "Jobs in dead-letter state")
JOBS_QUEUED = Gauge("jobs_queued", "Jobs waiting")
INGESTION_RUNS = Counter("ingestion_runs_total", "Ingestion runs", ["source", "status"])
QUARANTINE_OPEN = Gauge("quarantine_open_items", "Open quarantine items")
SOURCE_STALENESS = Gauge("source_staleness_hours", "Hours since last successful ingestion", ["source"])
SOURCE_STALE = Gauge("source_freshness_breached", "1 if a source breached its freshness SLA", ["source"])
ASSISTANT_QUERIES = Counter("assistant_queries_total", "Assistant queries", ["provider", "status"])
ASSISTANT_TOKENS = Counter("assistant_tokens_total", "LLM tokens", ["provider", "direction"])
AUTHZ_DENIALS = Counter("authz_denials_total", "Authorization denials", ["reason"])


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
            "tenant_id": tenant_var.get(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True  # replaced by our access log


def log(logger: logging.Logger, level: int, msg: str, **fields: object) -> None:
    logger.log(level, msg, extra={"fields": fields})


access_logger = logging.getLogger("access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        if len(rid) > 64 or not rid.replace("-", "").isalnum():
            rid = uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status = 500
        try:
            response: Response = await call_next(request)
            status = response.status_code
            response.headers["x-request-id"] = rid
            return response
        finally:
            elapsed = time.perf_counter() - start
            route = request.scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            HTTP_REQUESTS.labels(request.method, route_path, str(status)).inc()
            HTTP_LATENCY.labels(request.method, route_path).observe(elapsed)
            log(access_logger, logging.INFO, "request", method=request.method, route=route_path,
                status=status, duration_ms=round(elapsed * 1000, 2))
            request_id_var.reset(token)
