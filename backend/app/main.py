import asyncio
import logging
from logging.handlers import RotatingFileHandler
import time
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import inspect, text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.interview_routes import router as interview_router
from app.api.identity_routes import router as identity_router
from app.api.candidate_routes import router as candidate_router
from app.api.recommendation_routes import router as recommendation_router
from app.api.workflow_routes import router as workflow_router
from app.api.auth_routes import router as auth_router
from app.api.job_routes import router as job_router
from app.api.resume_routes import router as resume_router
from app.api.scheduling_routes import router as scheduling_router
from app.api.program_routes import router as program_router
from app.api.application_routes import router as application_router
from app.config import refresh_smtp_settings, settings
from app.core.exceptions import AppException
from app.core.logging import ctx_request_id, log_event
from app.core.metrics import get_metrics_collector
from app.core.paths import get_backend_dir, resolve_path

logger = logging.getLogger("api")

# Keep unexpected API tracebacks available after the server console closes.
# The log intentionally captures only server-side exceptions, not request bodies.
_error_log_dir = get_backend_dir() / "data" / "logs"
_error_log_dir.mkdir(parents=True, exist_ok=True)
_error_log_path = _error_log_dir / "server-errors.log"
if not any(
    isinstance(handler, RotatingFileHandler)
    and Path(getattr(handler, "baseFilename", "")).resolve() == _error_log_path.resolve()
    for handler in logger.handlers
):
    _error_handler = RotatingFileHandler(
        _error_log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    _error_handler.setLevel(logging.ERROR)
    _error_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_error_handler)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Fail-fast production startup validation and schema creation."""
    if settings.environment == "production":
        settings.validate_production_readiness()
    from app.database.base import Base
    from app.database.connection import engine
    import app.database.models
    Base.metadata.create_all(bind=engine)
    if inspect(engine).has_table("resumes"):
        resume_columns = {column["name"] for column in inspect(engine).get_columns("resumes")}
        if "original_filename" not in resume_columns:
            with engine.begin() as connection:
                connection.exec_driver_sql("ALTER TABLE resumes ADD COLUMN original_filename VARCHAR(255)")
    if inspect(engine).has_table("interview_sessions"):
        session_columns = {column["name"] for column in inspect(engine).get_columns("interview_sessions")}
        gaze_columns = {
            "gaze_warning_count": "INTEGER NOT NULL DEFAULT 0",
            "gaze_flagged": "BOOLEAN NOT NULL DEFAULT FALSE",
            "gaze_flagged_at": "TIMESTAMP NULL",
            "gaze_events": "JSON NOT NULL DEFAULT '[]'",
        }
        with engine.begin() as connection:
            for column_name, column_definition in gaze_columns.items():
                if column_name not in session_columns:
                    connection.exec_driver_sql(
                        f"ALTER TABLE interview_sessions ADD COLUMN {column_name} {column_definition}"
                    )
    from app.api.scheduling_routes import scheduling_reminder_loop
    reminder_task = asyncio.create_task(scheduling_reminder_loop(), name="schedule-reminders")
    try:
        yield
    finally:
        reminder_task.cancel()
        with suppress(asyncio.CancelledError):
            await reminder_task


from app.security.security_headers import SecurityHeadersMiddleware

app = FastAPI(
    title="AI Hiring Pipeline",
    lifespan=lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)





@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """
    Ensures every request has a traceable request_id in request.state, ContextVars,
    and X-Request-ID response header, while recording latency metrics.
    """
    request_id = request.headers.get("X-Request-ID")
    if not request_id:
        request_id = f"req_{uuid.uuid4().hex[:10]}"
    request.state.request_id = request_id
    token = ctx_request_id.set(request_id)

    t0 = time.time()
    try:
        response = await call_next(request)
    finally:
        ctx_request_id.reset(token)

    response.headers["X-Request-ID"] = request_id
    get_metrics_collector().record_request(response.status_code)
    return response


def _get_request_id(request: Request) -> str:
    return (
        getattr(request.state, "request_id", None)
        or request.headers.get("X-Request-ID")
        or f"req_{uuid.uuid4().hex[:10]}"
    )


# ---------------------------------------------------------------------------
# Centralized Error Handlers (D3.2, D3.6)
# ---------------------------------------------------------------------------

@app.exception_handler(AppException)
async def handle_app_exception(request: Request, exc: AppException):
    req_id = _get_request_id(request)
    content = {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "request_id": req_id,
        },
        "detail": exc.message,
    }
    if exc.details is not None:
        content["error"]["details"] = exc.details

    response = JSONResponse(
        status_code=exc.status_code,
        content=content,
    )
    response.headers["X-Request-ID"] = req_id
    return response


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    req_id = _get_request_id(request)
    errors = exc.errors()
    msg = "Request validation failed"
    if errors:
        field = errors[0].get("loc", ["field"])[-1]
        msg = f"Invalid input for '{field}': {errors[0].get('msg', 'validation error')}"

    response = JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "INVALID_REQUEST",
                "message": msg,
                "request_id": req_id,
                "details": errors,
            },
            "detail": msg,
        },
    )
    response.headers["X-Request-ID"] = req_id
    return response


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(request: Request, exc: StarletteHTTPException):
    req_id = _get_request_id(request)
    detail_str = str(exc.detail) if exc.detail else "HTTP error"

    code_map = {
        400: "INVALID_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "INVALID_INPUT",
        503: "SERVICE_UNAVAILABLE",
    }
    code = code_map.get(exc.status_code, f"HTTP_{exc.status_code}")

    if exc.status_code == 404:
        if "interview" in detail_str.lower() or "session" in detail_str.lower():
            code = "INTERVIEW_NOT_FOUND"
        elif "candidate" in detail_str.lower():
            code = "CANDIDATE_NOT_FOUND"
        elif "workflow" in detail_str.lower():
            code = "WORKFLOW_NOT_FOUND"

    response = JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": code,
                "message": detail_str,
                "request_id": req_id,
            },
            "detail": detail_str,
        },
        headers=getattr(exc, "headers", None) or {},
    )
    response.headers["X-Request-ID"] = req_id
    return response


@app.exception_handler(Exception)
async def handle_unexpected_exception(request: Request, exc: Exception):
    req_id = _get_request_id(request)
    logger.exception("Unexpected error [request_id=%s]: %s", req_id, exc)

    log_event(
        "unexpected_exception",
        level="ERROR",
        request_id=req_id,
        error_type=type(exc).__name__,
        message=str(exc),
    )

    response = JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred.",
                "request_id": req_id,
            },
            "detail": "An unexpected error occurred.",
        },
    )
    response.headers["X-Request-ID"] = req_id
    return response

app.include_router(auth_router)
app.include_router(interview_router)
app.include_router(identity_router)
app.include_router(candidate_router)
app.include_router(recommendation_router)
app.include_router(workflow_router)
app.include_router(job_router)
app.include_router(resume_router)
app.include_router(scheduling_router)
app.include_router(program_router)
app.include_router(application_router)


@app.get("/")
def home_page():
    """Public product landing page with an interactive, local demo."""
    ui_path = Path("static/home.html")
    if not ui_path.exists():
        ui_path = Path(__file__).resolve().parent.parent / "static" / "home.html"
    return FileResponse(ui_path, headers={"Cache-Control": "no-store, max-age=0"})


@app.get("/signin")
@app.get("/student/signin")
@app.get("/recruiter/signin")
def signin_page():
    ui_path = Path("static/signin.html")
    if not ui_path.exists():
        ui_path = Path(__file__).resolve().parent.parent / "static" / "signin.html"
    return FileResponse(ui_path, headers={"Cache-Control": "no-store, max-age=0"})


@app.get("/health")
def health():
    refresh_smtp_settings()
    return {
        "status": "ok",
        "alive": True,
        "services": {
            "api": "ok",
            "email": "configured" if settings.smtp_host and settings.smtp_from_email else "not_configured",
        },
    }


@app.get("/ready")
def ready(response: Response):
    services = {
        "database": "ok",
        "redis": "ok",
        "identity_model": "ok",
        "llm": "ok",
    }
    status = "ready"
    reason = None

    # 1. Database connection probe
    if not settings.database_url:
        services["database"] = "error"
        status = "not_ready"
        reason = reason or "database_unavailable"
        response.status_code = 503
    else:
        try:
            from app.database.connection import engine
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            services["database"] = "error"
            status = "not_ready"
            reason = reason or "database_unavailable"
            response.status_code = 503

    # 2. Redis connection probe
    redis_url = getattr(settings, "redis_url", "")
    if redis_url or getattr(settings, "redis_required", False):
        try:
            import redis
            r = redis.from_url(redis_url or "redis://localhost:6379/0", socket_connect_timeout=0.5)
            r.ping()
        except Exception:
            services["redis"] = "error"
            status = "not_ready"
            reason = reason or "redis_unavailable"
            response.status_code = 503

    # 3. Identity models
    sface_path = resolve_path(settings.sface_model_path)
    yunet_path = resolve_path(settings.yunet_model_path)
    if not sface_path.exists() or not yunet_path.exists():
        services["identity_model"] = "error"
        status = "not_ready"
        reason = "identity_model_unavailable"
        response.status_code = 503

    # 4. LLM check: this app currently supports NVIDIA only, and a provider
    # name without credentials is not enough to score resumes or interviews.
    llm_configured = (
        settings.llm_provider == "nvidia"
        and bool(settings.nvidia_api_key and settings.nvidia_api_key.strip())
    )
    if not llm_configured:
        services["llm"] = "error"
        status = "not_ready"
        reason = reason or "llm_unavailable"
        response.status_code = 503

    body = {
        "status": status,
        "services": services,
    }
    if reason:
        body["reason"] = reason

    return body


@app.get("/metrics")
def get_metrics():
    return get_metrics_collector().get_metrics()


@app.get("/interview-ui")
def interview_ui():
    ui_path = Path("static/interview.html")
    if not ui_path.exists():
        ui_path = Path(__file__).resolve().parent.parent / "static" / "interview.html"
    return FileResponse(ui_path, headers={"Cache-Control": "no-store, max-age=0"})


@app.get("/recruiter-ui")
@app.get("/recruiter")
def recruiter_ui():
    ui_path = Path("static/program-admin.html")
    if not ui_path.exists():
        ui_path = Path(__file__).resolve().parent.parent / "static" / "program-admin.html"
    return FileResponse(ui_path, headers={"Cache-Control": "no-store, max-age=0"})


@app.get("/student")
@app.get("/apply")
def apply_ui():
    ui_path = Path("static/apply.html")
    if not ui_path.exists():
        ui_path = Path(__file__).resolve().parent.parent / "static" / "apply.html"
    return FileResponse(ui_path, headers={"Cache-Control": "no-store, max-age=0"})


@app.get("/program-admin")
def program_admin_ui():
    return RedirectResponse(url="/recruiter", status_code=307)


# ---------------------------------------------------------------------------
# Diagnostic & Failure Simulation Endpoints (Used for D3 integration tests)
# ---------------------------------------------------------------------------

@app.get("/test/simulate-error")
def simulate_unexpected_error():
    raise RuntimeError("Simulated unexpected backend database failure")


@app.get("/test/simulate-llm-failure")
def simulate_llm_failure():
    from app.core.exceptions import LLMUnavailableException
    raise LLMUnavailableException("Simulated LLM connection timeout")


@app.get("/test/simulate-stt-failure")
def simulate_stt_failure():
    from app.core.exceptions import STTUnavailableException
    raise STTUnavailableException("Simulated STT speech recognition failure")

