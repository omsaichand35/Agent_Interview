"""Browser Security Headers Middleware (Requirement F3.7).

Enforces essential defense-in-depth HTTP response headers:
- Strict-Transport-Security (HSTS)
- X-Content-Type-Options (MIME sniffing prevention)
- X-Frame-Options (Clickjacking defense)
- Referrer-Policy
- Content-Security-Policy (CSP)
- Permissions-Policy (Restricting hardware APIs)
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects modern browser security headers on all API and static responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)

        # 1. Prevent MIME-type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # 2. Clickjacking defense (disallow embedding in iframes)
        response.headers["X-Frame-Options"] = "DENY"

        # 3. Referrer information restriction
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # 4. Enforce HTTPS in supporting clients
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # 5. Content Security Policy (permitting UI assets and WebSocket streams)
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' https://cdn.jsdelivr.net",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com",
            "img-src 'self' data: blob:",
            "media-src 'self' blob:",
            "connect-src 'self' ws: wss: http: https:",
            "frame-ancestors 'none'",
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_directives)

        # 6. Hardware access permissions policy
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(self), geolocation=()"

        return response
