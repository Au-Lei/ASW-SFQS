"""T04 bootstrap only; directory and quotation repositories are later tasks."""
import hashlib
import json
from typing import Annotated

from fastapi import APIRouter, Header, Request, Response, Security
from fastapi.security import APIKeyCookie

from backend.app.core.boundary import COOKIE_NAME
from backend.app.core.settings import ROOT
from backend.app.domain.contracts import BootstrapResponse, HealthResponse, SessionResponse


def load_seed_summary():
    data = json.loads((ROOT/"config/seeds/qingdao-v1.json").read_text(encoding="utf-8"))
    canonical = json.dumps({k:v for k,v in data.items() if k!="content_sha256"},ensure_ascii=False,sort_keys=True,separators=(",", ":"))
    if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != data["content_sha256"]:
        raise RuntimeError("SEED_CHECKSUM_MISMATCH")
    countries = {c["id"]:c for c in data["country_regions"]}
    result=[]
    for region in data["regions"]:
        routes=[r for r in data["route_groups"] if r["region_id"]==region["id"]]
        ids={r["id"] for r in routes}
        destinations=[d for d in data["destinations"] if d["route_group_id"] in ids]
        result.append({"id":region["id"],"name":region["name"],"destination_count":len(destinations),
            "route_group_count":len(routes),"route_names":[r["name"] for r in routes],
            "preview_destinations":[{"id":d["id"],"name_en":d["display_name_en"],"name_zh":d["display_name_zh"],
                "country_zh":countries[d["country_region_id"]]["name_zh"]} for d in destinations[:6]]})
    return result


router = APIRouter(prefix="/api/v1", tags=["system"])
session_cookie_schema=APIKeyCookie(name=COOKIE_NAME,scheme_name="LocalSessionCookie",
    description="本机HttpOnly会话，写请求还需要受信Origin和对应CSRF令牌；不是局域网用户认证。")


@router.get("/health",response_model=HealthResponse)
def health(request: Request):
    return HealthResponse(status="ok",version="0.1.0",stage="T04",database_status="NOT_INITIALIZED",
                          model_status=request.app.state.settings.model_status)


@router.get("/bootstrap",response_model=BootstrapResponse)
def bootstrap(request: Request,response: Response):
    sessions=request.app.state.sessions
    cookie=request.cookies.get(COOKIE_NAME)
    if not sessions.valid(cookie):
        cookie=sessions.create()
        response.set_cookie(COOKIE_NAME,cookie,httponly=True,samesite="strict",secure=False,path="/",max_age=43200)
    return BootstrapResponse(origin_name="青岛港",regions=request.app.state.seed_summary,
        quotation_status="NOT_INITIALIZED",model_status=request.app.state.settings.model_status,
        csrf_token=sessions.csrf(cookie))


@router.post("/session/verify",response_model=SessionResponse)
def verify_session(origin: Annotated[str,Header(alias="Origin")],
                   csrf_token: Annotated[str,Header(alias="X-CSRF-Token")],
                   session_cookie: Annotated[str,Security(session_cookie_schema)]):
    return SessionResponse(status="VALID")
