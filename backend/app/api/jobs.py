"""Local, session-protected status and bounded task controls. No upload API yet."""
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Security
from fastapi.exceptions import HTTPException
from fastapi.security import APIKeyCookie

from backend.app.core.boundary import COOKIE_NAME, error_response
from backend.app.domain.contracts import JobCommandRequest, JobView
from backend.app.domain.errors import DomainError
from backend.app.repositories.database import make_engine, schema_status
from backend.app.repositories.jobs import ERROR_CODES, JobQueue


router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])
job_cookie = APIKeyCookie(name=COOKIE_NAME, scheme_name="LocalSessionCookie", auto_error=False)


def authenticated(request: Request, cookie: str | None = Security(job_cookie)):
    if not request.app.state.sessions.valid(cookie):
        raise HTTPException(403)


def write_headers(origin: Annotated[str, Header(alias="Origin")],
                  csrf: Annotated[str, Header(alias="X-CSRF-Token")]):
    """Declare middleware-enforced headers in the runtime OpenAPI as well."""


def view(job, retry_id=None):
    error_code = job.error.get("code") if isinstance(job.error, dict) else ("JOB_FAILED" if job.error else None)
    if error_code is not None and error_code not in ERROR_CODES:
        error_code = "JOB_FAILED"
    return JobView(id=job.id, kind=job.kind if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", job.kind) else "UNKNOWN",
        state=job.state, stage=job.stage if job.stage and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", job.stage) else None,
        version=job.version, progress_done=job.progress_done, progress_total=job.progress_total,
        attempts=job.attempts, max_attempts=job.max_attempts, cancel_requested=job.cancel_requested,
        available_at=job.available_at.isoformat() if job.available_at else None,
        created_at=job.created_at.isoformat(), updated_at=job.updated_at.isoformat(),
        error_code=error_code, result_available=job.state == "SUCCEEDED" and bool(job.result_ref), retry_job_id=retry_id)


def operate(request, job_id, *, action=None, expected_version=None):
    url = request.app.state.settings.database_url
    if schema_status(url) != "READY":
        return error_response("SERVICE_UNAVAILABLE", "数据库结构尚未就绪，请先完成显式迁移", 503, request.state.request_id)
    engine = make_engine(url)
    try:
        queue = JobQueue(engine)
        if action == "cancel":
            queue.cancel(job_id, expected_version)
        if action == "retry":
            new = queue.retry(job_id, expected_version)
            job_id = new.id
        job, retry = queue.get(job_id)
        return view(job, retry)
    except DomainError as error:
        if error.code == "JOB_NOT_FOUND":
            return error_response("NOT_FOUND", "任务不存在", 404, request.state.request_id)
        if error.code == "VERSION_CONFLICT":
            return error_response("VERSION_CONFLICT", "任务状态已改变，请刷新后重试", 409, request.state.request_id)
        return error_response("ACTION_BLOCKED", "当前任务状态不支持此操作", 422, request.state.request_id)
    finally:
        engine.dispose()


@router.get("/{id}", response_model=JobView, dependencies=[Depends(authenticated)])
def read_job(id: UUID, request: Request):
    return operate(request, id)


@router.post("/{id}/cancel", response_model=JobView, dependencies=[Depends(authenticated), Depends(write_headers)])
def cancel_job(id: UUID, body: JobCommandRequest, request: Request):
    return operate(request, id, action="cancel", expected_version=body.expected_version)


@router.post("/{id}/retry", response_model=JobView, dependencies=[Depends(authenticated), Depends(write_headers)])
def retry_job(id: UUID, body: JobCommandRequest, request: Request):
    return operate(request, id, action="retry", expected_version=body.expected_version)
