"""Explicit browser origins and separate partitioned sessions for the hosted UI."""

import os
import re
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders, URL
from starlette.responses import JSONResponse, Response


LOCAL_SESSION_COOKIE = "neocare_session"
CLOUD_SESSION_COOKIE = "__Host-neocare_cloud_session"
ALLOWED_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")


def allowed_web_origins():
    """Read after deployment settings load; never allow wildcard/path origins."""
    raw = os.getenv("NEOCARE_WEB_ORIGINS", "")
    if not raw.strip():
        return frozenset()
    origins = set()
    for entry in raw.split(","):
        origin = entry.strip()
        try:
            parsed = urlsplit(origin)
            valid = (
                parsed.scheme == "https" and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None
                and not parsed.path and not parsed.query and not parsed.fragment
                and re.fullmatch(r"[a-z0-9.-]+", parsed.hostname) is not None
                and "*" not in origin and parsed.port != 0
                and origin == f"https://{parsed.netloc}"
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("NEOCARE_WEB_ORIGINS must contain explicit HTTPS origins without paths or wildcards.")
        origins.add(origin)
    return frozenset(origins)


def session_cookie_name(request):
    # Selection is set only by the outer origin guard. Untrusted origins never
    # reach handlers, and a cloud request never falls back to a local cookie.
    return CLOUD_SESSION_COOKIE if request.scope.get("neocare_cloud_origin") else LOCAL_SESSION_COOKIE


def _partition_latest_cookie(response, name):
    """Python3.13 cannot use Starlette's partitioned=True; amend only our cookie."""
    prefix = (name + "=").encode("ascii")
    for index in range(len(response.raw_headers) - 1, -1, -1):
        header, value = response.raw_headers[index]
        if header.lower() == b"set-cookie" and value.startswith(prefix):
            response.raw_headers[index] = (header, value + b"; Partitioned")
            return
    raise RuntimeError("The expected session cookie was not emitted.")


def set_session_cookie(response, request, token, max_age):
    name = session_cookie_name(request)
    cloud = name == CLOUD_SESSION_COOKIE
    response.set_cookie(
        name, token, max_age=max_age, path="/", httponly=True,
        secure=cloud or request.url.scheme == "https", samesite="none" if cloud else "lax",
    )
    if cloud:
        _partition_latest_cookie(response, name)


def clear_session_cookie(response, request):
    name = session_cookie_name(request)
    cloud = name == CLOUD_SESSION_COOKIE
    response.delete_cookie(
        name, path="/", httponly=True, secure=cloud or request.url.scheme == "https",
        samesite="none" if cloud else "lax",
    )
    if cloud:
        _partition_latest_cookie(response, name)


class HostedUIAccessMiddleware:
    """Outer ASGI guard: enforce origins before routing, including sign-in.

    Wrapping Starlette's error middleware also gives trusted browsers CORS
    headers on validation/authentication errors and generated500 responses.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_private_response(message):
            if message["type"] == "http.response.start" and scope.get("path", "").startswith("/api/"):
                # Cover early guard failures as well as routed responses and
                # outer server errors. Neither browsers nor shared caches may
                # retain API data, including patient JSON and downloadable PDFs.
                MutableHeaders(scope=message)["Cache-Control"] = "private, no-store"
            await send(message)

        headers = Headers(scope=scope)
        origin_headers = headers.getlist("origin")
        origin = origin_headers[0] if len(origin_headers) == 1 else None
        scope["neocare_cloud_origin"] = None
        try:
            allowed = allowed_web_origins()
        except ValueError:
            return await JSONResponse({"detail": "Hosted interface origins are not configured correctly."}, status_code=503)(scope, receive, send_private_response)
        url = URL(scope=scope)
        same_origin = f"{url.scheme}://{url.netloc}"
        cloud = bool(origin and origin != same_origin and origin in allowed)

        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                # Also vary no-Origin responses so caches cannot reuse their
                # absence of CORS headers for a hosted-interface request.
                response_headers.add_vary_header("Origin")
                if cloud:
                    response_headers["Access-Control-Allow-Origin"] = origin
                    response_headers["Access-Control-Allow-Credentials"] = "true"
            await send_private_response(message)

        if origin_headers and (len(origin_headers) != 1 or (origin != same_origin and not cloud)):
            return await JSONResponse({"detail": "This browser origin is not allowed."}, status_code=403)(scope, receive, send_with_cors)
        if cloud:
            scope["neocare_cloud_origin"] = origin
            if scope["method"] == "OPTIONS" and headers.get("access-control-request-method"):
                requested_method = headers["access-control-request-method"]
                requested_headers = {
                    item.strip().lower() for item in headers.get("access-control-request-headers", "").split(",") if item.strip()
                }
                if requested_method not in ALLOWED_METHODS or requested_headers - {"content-type"}:
                    return await JSONResponse({"detail": "This cross-origin request is not allowed."}, status_code=403)(scope, receive, send_with_cors)
                response = Response(status_code=204, headers={
                    "Access-Control-Allow-Methods": ", ".join(ALLOWED_METHODS),
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Access-Control-Max-Age": "600",
                })
                return await response(scope, receive, send_with_cors)
            if scope["method"] not in ALLOWED_METHODS or headers.get("authorization") or headers.get("x-api-key"):
                return await JSONResponse({"detail": "This cross-origin request is not allowed."}, status_code=403)(scope, receive, send_with_cors)
        await self.app(scope, receive, send_with_cors)
