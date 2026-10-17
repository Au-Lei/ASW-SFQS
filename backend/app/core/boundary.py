"""Loopback browser boundary and process-scoped, signed local sessions.

Origin checking and a cookie-bound CSRF token protect every unsafe method.
This is local browser protection, not authentication for a LAN deployment.
"""
import hashlib
import hmac
import logging
import re
import secrets
from uuid import uuid4

from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.app.domain.contracts import ErrorResponse

COOKIE_NAME = "asw_local_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LOGGER = logging.getLogger("asw.requests")


def error_response(code: str, message: str, status: int, request_id: str, details=None):
    body = ErrorResponse(error={"code":code,"message":message,"request_id":request_id,"details":details or []})
    return JSONResponse(body.model_dump(mode="json"), status_code=status)


class LocalSession:
    def __init__(self):
        self._secret = secrets.token_bytes(32)

    def _sign(self, purpose: str, token: str) -> str:
        return hmac.new(self._secret, (purpose+":"+token).encode("ascii"), hashlib.sha256).hexdigest()

    def create(self) -> str:
        token = secrets.token_urlsafe(32)
        return token+"."+self._sign("session", token)

    def valid(self, cookie: str | None) -> bool:
        if not cookie or not re.fullmatch(r"[A-Za-z0-9_-]{43}\.[a-f0-9]{64}", cookie):
            return False
        token, signature = cookie.split(".")
        return hmac.compare_digest(signature, self._sign("session", token))

    def csrf(self, cookie: str) -> str:
        return self._sign("csrf", cookie)


class LocalBoundary:
    def __init__(self, app, *, settings, session):
        self.app, self.settings, self.session = app, settings, session

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope, receive=receive)
        supplied = request.headers.get("x-request-id", "")
        request_id = supplied if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", supplied) else str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        response_started=False

        async def safe_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started=True
                headers = [(k,v) for k,v in message.get("headers", []) if k.lower() not in
                           (b"x-request-id", b"cache-control", b"x-content-type-options", b"x-frame-options")]
                headers += [(b"x-request-id",request_id.encode("ascii")),(b"cache-control",b"no-store"),
                            (b"x-content-type-options",b"nosniff"),(b"x-frame-options",b"DENY")]
                message = {**message,"headers":headers}
            await send(message)

        async def deny(code, message, status=403):
            await error_response(code,message,status,request_id)(scope,receive,safe_send)

        authority = request.headers.get("host", "").lower()
        if authority not in self.settings.allowed_authorities:
            return await deny("BAD_REQUEST", "当前地址不在本机服务允许范围内", 400)
        origin = request.headers.get("origin")
        if origin is not None and origin not in self.settings.allowed_origins:
            return await deny("FORBIDDEN", "请求来源不受信任")
        if request.headers.get("sec-fetch-site") == "cross-site":
            return await deny("FORBIDDEN", "不允许跨站访问本机服务")
        if request.method not in SAFE_METHODS:
            cookie = request.cookies.get(COOKIE_NAME)
            csrf = request.headers.get("x-csrf-token", "")
            if origin is None or not self.session.valid(cookie):
                return await deny("FORBIDDEN", "本机会话无效，请刷新页面")
            if not re.fullmatch(r"[a-f0-9]{64}", csrf) or not hmac.compare_digest(csrf, self.session.csrf(cookie)):
                return await deny("FORBIDDEN", "请求校验失败，请刷新页面")
        try:
            await self.app(scope,receive,safe_send)
        except Exception:
            # Never include exception strings, request bodies or secret configuration.
            LOGGER.error("request_failed request_id=%s", request_id)
            if response_started:
                # A streaming response cannot be replaced after its headers are sent.
                raise
            await error_response("INTERNAL_ERROR","服务暂时不可用，请稍后重试",500,request_id)(scope,receive,safe_send)
