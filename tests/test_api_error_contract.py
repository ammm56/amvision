"""FastAPI 统一公开错误外层测试。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from backend.service.api.error_handlers import register_exception_handlers


class _RequestBody(BaseModel):
    """用于验证请求错误不回显输入。"""

    count: int


def _build_test_application() -> FastAPI:
    """创建只包含错误处理边界的最小应用。"""

    application = FastAPI()
    register_exception_handlers(application)

    @application.post("/validate")
    async def validate(body: _RequestBody) -> dict[str, int]:
        return {"count": body.count}

    @application.get("/unexpected")
    async def unexpected() -> None:
        raise RuntimeError("private-runtime-marker")

    return application


def test_request_validation_error_has_fixed_sanitized_shape() -> None:
    """请求校验错误只返回有界定位信息，不包含原始输入。"""

    marker = "private-input-marker"
    with TestClient(_build_test_application()) as client:
        response = client.post("/validate", json={"count": marker})

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "request_validation_failed",
            "message": "请求参数校验失败",
            "details": {
                "errors": [
                    {
                        "path": ["body", "count"],
                        "rule": "int_parsing",
                        "reason": "请求字段校验失败",
                    }
                ],
                "error_count": 1,
                "returned_error_count": 1,
            },
        }
    }
    assert marker not in response.text


def test_unexpected_error_does_not_expose_exception_text() -> None:
    """未处理异常只返回通用错误，不公开异常文本和类型。"""

    with TestClient(
        _build_test_application(),
        raise_server_exceptions=False,
    ) as client:
        response = client.get("/unexpected")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "内部错误",
            "details": {},
        }
    }
    assert "private-runtime-marker" not in response.text
    assert "RuntimeError" not in response.text


def test_framework_http_errors_use_the_same_public_shape() -> None:
    """框架产生的 404 和 405 不得回退为默认 detail 外层。"""

    with TestClient(_build_test_application()) as client:
        not_found_response = client.get("/missing")
        method_response = client.get("/validate")

    assert not_found_response.status_code == 404
    assert not_found_response.json() == {
        "error": {
            "code": "resource_not_found",
            "message": "请求的资源不存在",
            "details": {},
        }
    }
    assert method_response.status_code == 405
    assert method_response.headers["allow"] == "POST"
    assert method_response.json() == {
        "error": {
            "code": "method_not_allowed",
            "message": "请求方法不受支持",
            "details": {},
        }
    }
