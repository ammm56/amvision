"""detection inference 请求读取与 runtime 控制辅助函数。"""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi import Request
from starlette.datastructures import FormData

from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.models.inference.detection_inference_payloads import (
    DETECTION_INFERENCE_INPUT_TRANSPORT_STORAGE,
    DetectionInferenceInputSource,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)


DEFAULT_INFERENCE_SCORE_THRESHOLD = 0.3


def ensure_visible_detection_deployment(
    *,
    principal: AuthenticatedPrincipal,
    deployment_project_id: str,
    deployment_instance_id: str,
) -> None:
    """校验当前主体是否可以访问指定 detection DeploymentInstance。"""

    if principal.project_ids and deployment_project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            "找不到指定的 DeploymentInstance",
            details={"deployment_instance_id": deployment_instance_id},
        )


def matches_detection_inference_filters(
    *,
    task: object,
    deployment_instance_id: str | None,
) -> bool:
    """判断 detection 推理任务是否满足额外筛选条件。"""

    if deployment_instance_id is None:
        return True
    task_spec = dict(task.task_spec)
    return task_spec.get("deployment_instance_id") == deployment_instance_id


def require_running_detection_deployment_process(
    *,
    deployment_process_supervisor: DeploymentProcessSupervisor,
    process_config: object,
    runtime_mode: str,
) -> None:
    """校验目标 detection deployment 子进程已经处于 running 状态。"""

    status = deployment_process_supervisor.get_status(process_config)
    if status.process_state == "running":
        return
    raise InvalidRequestError(
        "当前 deployment 进程尚未启动，请先调用 start 或 warmup 接口",
        details={
            "deployment_instance_id": getattr(process_config, "deployment_instance_id", None),
            "runtime_mode": runtime_mode,
            "process_state": status.process_state,
            "required_actions": [f"{runtime_mode}/start", f"{runtime_mode}/warmup"],
        },
    )


async def read_detection_inference_request_payload(
    request: Request,
) -> tuple[dict[str, object], DetectionInferenceInputSource]:
    """按 content-type 读取 detection 推理请求，并保留 one-of 输入源信息。"""

    content_type = (request.headers.get("content-type") or "").lower()
    if content_type.startswith("multipart/form-data"):
        return await _read_detection_multipart_payload(request)
    if content_type.startswith("application/json") or not content_type:
        try:
            payload = await request.json()
        except Exception as error:
            raise InvalidRequestError("请求体不是合法的 JSON") from error
        if not isinstance(payload, dict):
            raise InvalidRequestError("请求体必须是 JSON 对象")
        normalized_payload = {str(key): value for key, value in payload.items()}
        return normalized_payload, DetectionInferenceInputSource(
            input_file_id=normalized_payload.get("input_file_id")
            if isinstance(normalized_payload.get("input_file_id"), str)
            else None,
            input_uri=normalized_payload.get("input_uri") if isinstance(normalized_payload.get("input_uri"), str) else None,
            image_base64=normalized_payload.get("image_base64")
            if isinstance(normalized_payload.get("image_base64"), str)
            else None,
        )
    raise InvalidRequestError(
        "当前仅支持 application/json 或 multipart/form-data 推理请求",
        details={"content_type": content_type},
    )


def resolve_detection_http_request_id(request: Request, *, prefix: str) -> str:
    """解析一个稳定的 detection HTTP 请求 id。"""

    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id.strip():
        return f"{prefix}-{request_id.strip()}"
    return f"{prefix}-{uuid4().hex}"


def read_detection_async_inference_service_id(request: Request) -> str | None:
    """读取当前 detection async inference service 稳定 id。"""

    value = getattr(request.app.state, "detection_async_inference_service_id", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def resolve_detection_requested_score_threshold(value: float | None) -> float:
    """解析 detection 推理阈值；未提供时回落到默认值。"""

    if isinstance(value, int | float):
        threshold = float(value)
    else:
        threshold = DEFAULT_INFERENCE_SCORE_THRESHOLD
    if threshold < 0 or threshold > 1:
        raise InvalidRequestError(
            "score_threshold 必须位于 0 到 1 之间",
            details={"score_threshold": threshold},
        )
    return threshold


async def _read_detection_multipart_payload(
    request: Request,
) -> tuple[dict[str, object], DetectionInferenceInputSource]:
    """读取 multipart/form-data detection 推理请求。"""

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
    payload = {
        "project_id": _read_optional_form_str(form, "project_id"),
        "deployment_instance_id": _read_optional_form_str(form, "deployment_instance_id"),
        "model_type": _read_optional_form_str(form, "model_type"),
        "input_file_id": _read_optional_form_str(form, "input_file_id"),
        "input_uri": _read_optional_form_str(form, "input_uri"),
        "image_base64": _read_optional_form_str(form, "image_base64"),
        "input_transport_mode": _read_optional_form_str(form, "input_transport_mode")
        or DETECTION_INFERENCE_INPUT_TRANSPORT_STORAGE,
        "score_threshold": _parse_optional_form_float(form.get("score_threshold"), field_name="score_threshold"),
        "save_result_image": _parse_optional_form_bool(
            form.get("save_result_image"),
            field_name="save_result_image",
            default=True,
        ),
        "return_preview_image_base64": _parse_optional_form_bool(
            form.get("return_preview_image_base64"),
            field_name="return_preview_image_base64",
            default=False,
        ),
        "extra_options": _parse_optional_form_json_dict(form.get("extra_options"), field_name="extra_options"),
        "display_name": _read_optional_form_str(form, "display_name") or "",
    }
    return payload, DetectionInferenceInputSource(
        input_file_id=payload.get("input_file_id") if isinstance(payload.get("input_file_id"), str) else None,
        input_uri=payload.get("input_uri") if isinstance(payload.get("input_uri"), str) else None,
        image_base64=payload.get("image_base64") if isinstance(payload.get("image_base64"), str) else None,
        upload_bytes=upload_bytes,
        upload_filename=upload_filename,
        upload_content_type=upload_content_type,
    )


def _read_optional_form_str(form: FormData, key: str) -> str | None:
    """从 multipart form 中读取可选字符串字段。"""

    value = form.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _parse_optional_form_float(value: object, *, field_name: str) -> float | None:
    """把 multipart form 字段解析为可选浮点数。"""

    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError as error:
            raise InvalidRequestError(
                f"{field_name} 必须是合法数字",
                details={field_name: value},
            ) from error
    raise InvalidRequestError(
        f"{field_name} 必须是合法数字",
        details={field_name: value},
    )


def _parse_optional_form_bool(value: object, *, field_name: str, default: bool) -> bool:
    """把 multipart form 字段解析为布尔值。"""

    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise InvalidRequestError(
        f"{field_name} 必须是合法布尔值",
        details={field_name: value},
    )


def _parse_optional_form_json_dict(value: object, *, field_name: str) -> dict[str, object]:
    """把 multipart form 中的 JSON 字段解析为字典。"""

    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise InvalidRequestError(
                f"{field_name} 不是合法 JSON",
                details={field_name: value},
            ) from error
        if isinstance(parsed, dict):
            return {str(key): item for key, item in parsed.items()}
    raise InvalidRequestError(
        f"{field_name} 必须是 JSON 对象",
        details={field_name: value},
    )
