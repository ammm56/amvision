"""service node 输出响应 helper。"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass

from backend.service.application.errors import ServiceConfigurationError


def build_response_body_output(value: object) -> dict[str, object]:
    """把 dataclass 或字典转换成 response-body.v1 输出。"""

    if is_dataclass(value):
        return {"body": asdict(value)}
    if isinstance(value, dict):
        return {"body": dict(value)}
    raise ServiceConfigurationError(
        "service node 返回值必须是 dataclass 或 dict",
        details={"value_type": type(value).__name__},
    )
