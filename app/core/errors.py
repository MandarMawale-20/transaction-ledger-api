"""Application errors and the single error envelope used by every response.

    {"error": {"code": "...", "message": "...", "details": {...}}}
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("ledger")


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"
    message = "Bad request."

    def __init__(self, message: str | None = None, details: dict | None = None):
        self.message = message or self.message
        self.details = details or {}
        super().__init__(self.message)


class AccountNotFound(AppError):
    status_code = 404
    code = "ACCOUNT_NOT_FOUND"
    message = "Account not found."


class InsufficientBalance(AppError):
    status_code = 409
    code = "INSUFFICIENT_BALANCE"
    message = "Account does not have sufficient balance."


class BalanceLimitExceeded(AppError):
    status_code = 409
    code = "BALANCE_LIMIT_EXCEEDED"
    message = "This operation would exceed the maximum supported balance."


class ReferenceConflict(AppError):
    status_code = 409
    code = "REFERENCE_ID_CONFLICT"
    message = "This reference_id was already used with a different request."


def error_body(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def _validation_code(errors: list[dict]) -> str:
    if not errors:
        return "VALIDATION_ERROR"
    loc = tuple(errors[0].get("loc", ()))
    if len(loc) >= 2 and loc[0] == "query" and loc[1] in ("limit", "offset"):
        return "INVALID_PAGINATION"
    if loc in (("body", "type"), ("query", "type")):
        return "INVALID_TRANSACTION_TYPE"
    if loc == ("body", "amount"):
        return "INVALID_AMOUNT"
    return "VALIDATION_ERROR"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError):
        errors = exc.errors()
        details = {
            "errors": [
                {
                    "field": ".".join(str(p) for p in e.get("loc", ())),
                    "message": e.get("msg", ""),
                    "type": e.get("type", ""),
                }
                for e in errors
            ]
        }
        return JSONResponse(
            status_code=422,
            content=error_body(
                _validation_code(errors), "Request validation failed.", details
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException):
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(codes.get(exc.status_code, "HTTP_ERROR"), str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception):
        logger.exception("Unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=error_body("INTERNAL_ERROR", "Internal server error."),
        )
