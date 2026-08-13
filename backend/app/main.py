import json
import logging
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import admin, auth, beta, datasets, health, history, product, saas, workspaces
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.observability import initialize_sentry, request_id_context

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": record.levelname, "logger": record.name, "message": record.getMessage()}
        for name in ("request_id", "method", "path", "status_code", "duration_ms", "user_id", "workspace_id", "dataset_id", "job_id", "run_id"):
            if hasattr(record, name): payload[name] = getattr(record, name)
        if record.exc_info: payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


handler = logging.StreamHandler(); handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
logger = logging.getLogger("datapilot")
settings = get_settings()
initialize_sentry(settings.sentry_dsn, settings.app_env or settings.environment)
if settings.environment_name == "production":
    readiness_errors = settings.readiness_errors()
    if readiness_errors:
        raise RuntimeError("Unsafe production configuration: " + " ".join(readiness_errors))
app = FastAPI(title=settings.app_name, version=settings.app_version)
if settings.trust_proxy_headers:
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(workspaces.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(beta.router, prefix="/api")
app.include_router(saas.router, prefix="/api")
app.include_router(datasets.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(product.router, prefix="/api")


@app.middleware("http")
async def security_and_request_logging(request: Request, call_next):
    started = perf_counter(); request_id = request.headers.get("X-Request-ID", str(uuid4()))[:100]
    request.state.request_id = request_id; token = request_id_context.set(request_id)
    try: response = await call_next(request)
    finally: request_id_context.reset(token)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    logger.info("request_complete", extra={"request_id": request_id, "method": request.method, "path": request.url.path, "status_code": response.status_code, "duration_ms": round((perf_counter() - started) * 1000, 2), "user_id": getattr(request.state, "user_id", None), "workspace_id": getattr(request.state, "workspace_id", None)})
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    from app.services.admin_metrics import record_system_error
    from app.services.product_analytics import ProductEvents, analysis_failure_category, record_product_event
    record_system_error(getattr(request.state, "request_id", None), exc.error_code, request.url.path, request.method, exc.status_code, exc.message, getattr(request.state, "user_id", None), getattr(request.state, "workspace_id", None))
    if any(segment in request.url.path for segment in ("/ask", "/analyze", "/chart")):
        record_product_event(ProductEvents.ANALYSIS_FAILED, getattr(request.state, "user_id", None), getattr(request.state, "workspace_id", None), properties={"failure_category": analysis_failure_category(exc.error_code)})
    return JSONResponse(status_code=exc.status_code, content={"success": False, "message": exc.message, "error_code": exc.error_code, "request_id": getattr(request.state, "request_id", None)})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [{"location": list(item["loc"]), "message": item["msg"], "type": item["type"]} for item in exc.errors()]
    return JSONResponse(status_code=422, content={"success": False, "message": "The request is invalid.", "error_code": "VALIDATION_ERROR", "request_id": getattr(request.state, "request_id", None), "details": details})


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled request error", exc_info=exc)
    from app.services.admin_metrics import record_system_error
    record_system_error(getattr(request.state, "request_id", None), "INTERNAL_ERROR", request.url.path, request.method, 500, "Unable to process the request.", getattr(request.state, "user_id", None), getattr(request.state, "workspace_id", None))
    if any(segment in request.url.path for segment in ("/ask", "/analyze", "/chart")):
        from app.services.product_analytics import ProductEvents, record_product_event
        record_product_event(ProductEvents.ANALYSIS_FAILED, getattr(request.state, "user_id", None), getattr(request.state, "workspace_id", None), properties={"failure_category": "system"})
    return JSONResponse(status_code=500, content={"success": False, "message": "Unable to process the request.", "error_code": "INTERNAL_ERROR", "request_id": getattr(request.state, "request_id", None)})
