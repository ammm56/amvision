"""FastAPI 异常处理器注册。"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.service.application.errors import ServiceError


def register_exception_handlers(application: FastAPI) -> None:
    """为 FastAPI 应用注册统一异常处理器。

    参数：
    - application：要注册异常处理器的 FastAPI 应用。
    """

    @application.exception_handler(ServiceError)
    async def handle_service_error(request: Request, error: ServiceError) -> JSONResponse:
        """把 ServiceError 转成稳定错误响应。

        参数：
        - request：当前 HTTP 请求。
        - error：被捕获的服务错误。

        返回：
        - 统一结构的 JSON 错误响应。
        """

        return _build_error_response(
            request=request,
            status_code=error.status_code,
            code=error.code,
            message=error.message,
            details=error.details,
        )

    @application.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        """把请求校验错误转成稳定错误响应。

        参数：
        - request：当前 HTTP 请求。
        - error：请求校验错误。

        返回：
        - 统一结构的 JSON 错误响应。
        """

        return _build_error_response(
            request=request,
            status_code=422,
            code="request_validation_failed",
            message="请求参数校验失败",
            details={"errors": error.errors()},
        )


def _build_error_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, object],
) -> JSONResponse:
    """构建统一错误响应。

    参数：
    - request：当前 HTTP 请求。
    - status_code：HTTP 状态码。
    - code：稳定错误码。
    - message：错误消息。
    - details：附加错误细节。

    返回：
    - JSON 错误响应。
    """

    request_id = getattr(request.state, "request_id", None)
    payload: dict[str, object] = {
        "error": {
            "code": code,
            "message": message,
            "details": details,
        }
    }
    if request_id is not None:
        payload["error"]["request_id"] = request_id

    response = JSONResponse(status_code=status_code, content=payload)
    if request_id is not None:
        response.headers.setdefault("x-request-id", request_id)

    return response