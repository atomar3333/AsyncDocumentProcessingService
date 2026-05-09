import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Inject correlation_id into structlog context and response headers."""

    async def dispatch(self, request: Request, call_next):
        correlation_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

        # Bind to structlog contextvars so all logs in this request include it
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            correlation_id=correlation_id,
            component="api",
        )

        # Stash on request state so route handlers can read it
        request.state.correlation_id = correlation_id

        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = correlation_id
        return response
