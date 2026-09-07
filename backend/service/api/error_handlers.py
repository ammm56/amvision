"""FastAPI 异常处理器注册。"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.contracts.errors import ErrorContract
from backend.service.application.errors import ServiceError
from backend.service.application.public_errors import (
    build_error_contract,
    build_service_error_contract,
)


MAX_PUBLIC_VALIDATION_ERRORS = 32
_LOGGER = logging.getLogger(__name__)
_HTTP_ERROR_DEFAULTS: dict[int, tuple[str, str]] = {
    400: ("invalid_request", "请求无效"),
    401: ("authentication_required", "需要身份认证"),
    403: ("permission_denied", "没有操作权限"),
    404: ("resource_not_found", "请求的资源不存在"),
    405: ("method_not_allowed", "请求方法不受支持"),
    409: ("conflict", "请求与当前状态冲突"),
    413: ("request_entity_too_large", "请求正文过大"),
    415: ("unsupported_media_type", "请求媒体类型不受支持"),
    429: ("rate_limit_exceeded", "请求过于频繁"),
    503: ("service_unavailable", "服务暂不可用"),
}


def register_exception_handlers(application: FastAPI) -> None:
    """为 FastAPI 应用注册统一异常处理器。

    参数：
    - application：要注册异常处理器的 FastAPI 应用。
    """

    @application.exception_handler(ServiceError)
    async def handle_service_error(
        request: Request, error: ServiceError
    ) -> JSONResponse:
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
            error=build_service_error_contract(error),
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

        serialized_errors = _serialize_validation_errors(error.errors())
        return _build_error_response(
            request=request,
            status_code=422,
            error=build_error_contract(
                code="request_validation_failed",
                message="请求参数校验失败",
                details={
                    "errors": serialized_errors,
                    "error_count": len(error.errors()),
                    "returned_error_count": len(serialized_errors),
                },
            ),
        )

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request,
        error: StarletteHTTPException,
    ) -> JSONResponse:
        """把框架级 404、405 等 HTTP 错误转成统一公开结构。"""

        code, message = _HTTP_ERROR_DEFAULTS.get(
            error.status_code,
            ("http_error", "请求失败"),
        )
        return _build_error_response(
            request=request,
            status_code=error.status_code,
            error=build_error_contract(code=code, message=message),
            headers=error.headers,
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request,
        error: Exception,
    ) -> JSONResponse:
        """把未处理异常收口为不含内部信息的固定响应。"""

        _LOGGER.error("API 未处理异常类型: %s", type(error).__name__)
        return _build_error_response(
            request=request,
            status_code=500,
            error=build_error_contract(
                code="internal_error",
                message="内部错误",
                details={},
            ),
        )


def _serialize_validation_errors(
    errors: list[dict[str, object]],
) -> list[dict[str, object]]:
    """把 Pydantic 错误转换为有界且不含原始 input 的公开结构。"""

    serialized: list[dict[str, object]] = []
    for error in errors[:MAX_PUBLIC_VALIDATION_ERRORS]:
        raw_location = error.get("loc")
        location = (
            [str(item) for item in raw_location]
            if isinstance(raw_location, list | tuple)
            else []
        )
        raw_rule = error.get("type")
        rule = (
            raw_rule.strip()
            if isinstance(raw_rule, str) and raw_rule.strip()
            else "validation_error"
        )
        serialized.append(
            {
                "path": location,
                "rule": rule,
                "reason": "请求字段校验失败",
            }
        )
    return serialized


def _build_error_response(
    *,
    request: Request,
    status_code: int,
    error: ErrorContract,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """构建统一错误响应。

    参数：
    - request：当前 HTTP 请求。
    - status_code：HTTP 状态码。
    - error：统一公开错误对象。

    返回：
    - JSON 错误响应。
    """

    request_id = getattr(request.state, "request_id", None)
    payload: dict[str, object] = {"error": error.model_dump(mode="json")}

    response = JSONResponse(
        status_code=status_code,
        content=payload,
        headers=dict(headers or {}),
    )
    if request_id is not None:
        response.headers.setdefault("x-request-id", request_id)

    return response
