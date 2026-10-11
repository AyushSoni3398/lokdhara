"""RFC 9457 problem details with stable error codes (docs/API_SPECIFICATION.md §1)."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

ERROR_TYPE_BASE = "https://lokdhara.example/errors/"
PROBLEM_JSON = "application/problem+json"


class ApiError(Exception):
    """An expected error with a stable machine-readable code the SPA can translate."""

    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.headers = headers


def _problem(status: int, code: str, title: str, detail: str | None = None) -> dict[str, object]:
    body: dict[str, object] = {
        "type": ERROR_TYPE_BASE + code,
        "title": title,
        "status": status,
        "code": code,
    }
    if detail:
        body["detail"] = detail
    return body


async def _api_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)  # noqa: S101 - registered for ApiError only
    return JSONResponse(
        _problem(exc.status, exc.code, exc.title, exc.detail),
        status_code=exc.status,
        media_type=PROBLEM_JSON,
        headers=exc.headers,
    )


async def _validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    body = _problem(422, "validation_failed", "The request is not valid.")
    # Report field locations and error types only; never echo submitted values (may be secrets).
    body["errors"] = [
        {"field": ".".join(str(part) for part in err["loc"][1:]), "code": err["type"]}
        for err in exc.errors()
    ]
    return JSONResponse(body, status_code=422, media_type=PROBLEM_JSON)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
