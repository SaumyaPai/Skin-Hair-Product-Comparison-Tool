"""One error shape for every endpoint, and never a raw technical crash message.

{"error": {"code": "...", "message": "...", "details": [...], "request_id": "..."}}
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("skincare")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: list | None = None):
        self.status, self.code, self.message, self.details = status, code, message, details or []


def error_body(request: Request, code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or [],
                      "request_id": getattr(request.state, "request_id", "")}}


def _respond(request: Request, status: int, code: str, message: str, details=None):
    request.state.error_code = code
    return JSONResponse(status_code=status, content=error_body(request, code, message, details))


def _friendly(err: dict) -> dict:
    loc = [str(x) for x in err.get("loc", []) if x not in ("body", "query")]
    field = ".".join(loc) if loc else "request"
    msg = err.get("msg", "invalid value").removeprefix("Value error, ")
    return {"field": field, "issue": msg}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return _respond(request, exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        details = [_friendly(e) for e in exc.errors()]
        first = details[0] if details else {"field": "request", "issue": "invalid"}
        message = f"Please check {first['field']}: {first['issue']}."
        return _respond(request, 422, "VALIDATION_ERROR", message, details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return _respond(request, 404, "NOT_FOUND", "There's no such address in this API.")
        return _respond(request, exc.status_code, "HTTP_ERROR", "This request isn't supported.")

    @app.exception_handler(Exception)
    async def _crash(request: Request, exc: Exception):
        # Full details go to the terminal log for you; the shopper only sees a safe message.
        log.exception("Unexpected error (request %s)", getattr(request.state, "request_id", ""))
        return _respond(request, 502, "INTERNAL_ERROR",
                        "Something went wrong on our side. Please try again.")
