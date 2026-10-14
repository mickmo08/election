"""ASGI application."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import admin, data, research, system
from .config import get_settings
from .observability import RequestContextMiddleware, configure_logging, log, request_id_var

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("app")

app = FastAPI(
    title="Election Intelligence Platform API",
    version="0.1.0",
    docs_url="/api/docs" if settings.environment != "production" else None,
    openapi_url="/api/openapi.json" if settings.environment != "production" else None,
)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["authorization", "x-tenant", "content-type", "x-request-id"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers.setdefault("x-content-type-options", "nosniff")
    response.headers.setdefault("referrer-policy", "no-referrer")
    response.headers.setdefault("x-frame-options", "DENY")
    response.headers.setdefault("cache-control", "no-store")
    if settings.environment in ("staging", "production"):
        response.headers.setdefault("strict-transport-security", "max-age=63072000; includeSubDomains")
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        {"detail": "invalid request", "errors": [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]},
        status_code=422,
    )


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    log(logger, logging.ERROR, "unhandled error", path=request.url.path, error=type(exc).__name__)
    logger.exception("unhandled")
    return JSONResponse({"detail": "internal error", "request_id": request_id_var.get()}, status_code=500)


app.include_router(system.router)
app.include_router(data.router)
app.include_router(research.router)
app.include_router(admin.router)
