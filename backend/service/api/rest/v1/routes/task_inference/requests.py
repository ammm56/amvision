"""通用 task inference 请求读取工具。"""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi import Request
from starlette.datastructures import FormData

from backend.service.application.errors import InvalidRequestError


async def read_inference_http_payload(
    request: Request,
) -> tuple[dict[str, object], dict[str, object]]:
    """按 content-type 读取 inference 请求体和输入源。"""

    content_type = (request.headers.get("content-type") or "").lower()
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("input_image")
        upload_bytes = None
        upload_filename = None
        upload_content_type = None
        if upload is not None:
            if not hasattr(upload, "read"):
                raise InvalidRequestError("input_image 必须是有效的上传文件")
            upload_bytes = await upload.read()
            upload_filename = getattr(upload, "filename", None)
            upload_content_type = getattr(upload, "content_type", None)
        payload = _normalize_form_payload(form)
        return payload, {
            "input_file_id": payload.get("input_file_id"),
            "input_uri": payload.get("input_uri"),
            "image_base64": payload.get("image_base64"),
            "upload_bytes": upload_bytes,
            "upload_filename": upload_filename,
            "upload_content_type": upload_content_type,
        }
    if content_type.startswith("application/json") or not content_type:
        try:
            payload = await request.json()
        except Exception as error:
            raise InvalidRequestError("请求体不是合法的 JSON") from error
        if not isinstance(payload, dict):
            raise InvalidRequestError("请求体必须是 JSON 对象")
        normalized_payload = {str(key): value for key, value in payload.items()}
        return normalized_payload, {
            "input_file_id": normalized_payload.get("input_file_id"),
            "input_uri": normalized_payload.get("input_uri"),
            "image_base64": normalized_payload.get("image_base64"),
            "upload_bytes": None,
            "upload_filename": None,
            "upload_content_type": None,
        }
    raise InvalidRequestError(
        "当前仅支持 application/json 或 multipart/form-data 推理请求",
        details={"content_type": content_type},
    )


def resolve_inference_http_request_id(request: Request, *, prefix: str) -> str:
    """解析一个稳定的 inference HTTP 请求 id。"""

    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id.strip():
        return f"{prefix}-{request_id.strip()}"
    return f"{prefix}-{uuid4().hex}"


def _normalize_form_payload(form: FormData) -> dict[str, object]:
    """把 multipart form 里的字段归一为普通字典。"""

    payload: dict[str, object] = {}
    for key, value in form.multi_items():
        if key == "input_image" or not isinstance(value, str):
            continue
        normalized_value = value.strip()
        if not normalized_value:
            payload[str(key)] = None
            continue
        if key == "extra_options":
            try:
                parsed = json.loads(normalized_value)
            except json.JSONDecodeError as error:
                raise InvalidRequestError(
                    "extra_options 不是合法 JSON",
                    details={"extra_options": normalized_value},
                ) from error
            if not isinstance(parsed, dict):
                raise InvalidRequestError("extra_options 必须是 JSON 对象")
            payload[str(key)] = {str(item_key): item for item_key, item in parsed.items()}
            continue
        payload[str(key)] = normalized_value
    return payload
