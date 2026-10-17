from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse

from backend.app.api.system import load_seed_summary, router
from backend.app.core.boundary import LocalBoundary, LocalSession, error_response
from backend.app.core.settings import ROOT, Settings
from backend.app.domain.contracts import ErrorResponse


def create_app(settings: Settings | None = None, *, frontend_dist=None):
    settings=settings or Settings()
    dist=frontend_dist if frontend_dist is not None else ROOT/"frontend/dist"

    @asynccontextmanager
    async def lifespan(app):
        app.state.seed_summary=load_seed_summary()
        if settings.app_env=="local" and not (dist/"index.html").is_file():
            raise RuntimeError("Frontend build missing: run npm run build --prefix frontend")
        yield

    app=FastAPI(title="ASW-SFQS",version="0.1.0",debug=False,lifespan=lifespan,
        docs_url=None,redoc_url=None,openapi_url="/api/v1/openapi.json",
        responses={s:{"model":ErrorResponse} for s in (400,403,404,405,422,500)})
    app.state.settings=settings
    app.state.sessions=LocalSession()
    app.add_middleware(LocalBoundary,settings=settings,session=app.state.sessions)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request,exc):
        codes={400:"BAD_REQUEST",403:"FORBIDDEN",404:"NOT_FOUND",405:"METHOD_NOT_ALLOWED"}
        messages={400:"请求格式不正确",403:"请求未通过访问校验",404:"请求的内容不存在",405:"此地址不支持该请求方式"}
        return error_response(codes.get(exc.status_code,"BAD_REQUEST"),messages.get(exc.status_code,"请求未完成"),
                              exc.status_code,request.state.request_id)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request,exc):
        details=[{"field_path":"/"+"/".join(str(x).replace("~","~0").replace("/","~1") for x in e["loc"]),
                  "code":"INVALID_FIELD","message":"字段格式不符合要求"} for e in exc.errors()]
        return error_response("VALIDATION_ERROR","请检查提交的字段",422,request.state.request_id,details)

    app.include_router(router)
    if settings.app_env=="local":
        app.mount("/assets",StaticFiles(directory=dist/"assets",check_dir=False),name="assets")

        @app.get("/",include_in_schema=False)
        def frontend():
            return FileResponse(dist/"index.html")

        @app.get("/favicon.svg",include_in_schema=False)
        def favicon():
            return FileResponse(dist/"favicon.svg")
    return app


app=create_app()
