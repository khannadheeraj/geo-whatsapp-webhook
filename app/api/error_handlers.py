import logging
import uuid

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.errors import ApiError


logger = logging.getLogger("geo-ias-api")


def error_body(code: str, message: str, request_id: str, field_errors=None):
    return {"error": {"code": code, "message": message, "fieldErrors": field_errors or {}, "requestId": request_id}}


async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", "")[:100] or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


async def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse(error_body(exc.code, exc.message, request.state.request_id, exc.field_errors), status_code=exc.status_code)


async def validation_error_handler(request: Request, exc: RequestValidationError):
    fields = {".".join(str(part) for part in error["loc"][1:]): error["msg"] for error in exc.errors()}
    return JSONResponse(error_body("REQUEST_VALIDATION_FAILED", "The request is invalid.", request.state.request_id, fields), status_code=422)


async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled API error requestId=%s errorType=%s", request.state.request_id, type(exc).__name__)
    return JSONResponse(error_body("INTERNAL_ERROR", "The request could not be completed.", request.state.request_id), status_code=500)
