"""对转换请求进行无副作用的来源和方案检查。"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StrictInt

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.conversion_report_downloads import _SERVICE_ENTRIES
from backend.service.api.rest.v1.routes.detection_conversion_tasks.services import DETECTION_CONVERSION_SERVICE_BY_MODEL_TYPE
from backend.service.application.errors import InvalidRequestError
from backend.service.application.project_access import require_explicit_project_access
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


conversion_preflight_router = APIRouter(prefix="/models", tags=["models"])
ConversionChoice = Literal["onnx", "onnx-optimized", "openvino-ir-fp32", "openvino-ir-fp16", "openvino-ir-int8", "tensorrt-engine-fp32", "tensorrt-engine-fp16", "tensorrt-engine-int8"]


class ConversionPreflightRequest(BaseModel):
    """转换预检所需的项目、来源和目标设置。"""

    project_id: str
    model_type: str
    source_model_version_id: str
    target: ConversionChoice
    runtime_profile_id: str | None = None
    onnx_opset_version: StrictInt | None = None
    input_shape_mode: Literal["static", "dynamic", "dynamic-batch"] = "static"
    int8_calibration: dict[str, object] | None = None
    int8_validation: dict[str, object] | None = None
    input_profile: dict[str, list[StrictInt]] | None = None
    workspace_gib: StrictInt | None = None


@conversion_preflight_router.post("/{task_type}/conversion-tasks/preview")
def preview_conversion(
    task_type: Literal["detection", "classification", "segmentation", "pose", "obb"],
    body: ConversionPreflightRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> dict[str, object]:
    """复用提交前的来源与方案校验，不创建任务、不检查执行环境。"""
    require_explicit_project_access(visible_project_ids=principal.project_ids, project_id=body.project_id)
    entries = DETECTION_CONVERSION_SERVICE_BY_MODEL_TYPE if task_type == "detection" else _SERVICE_ENTRIES[task_type]
    entry = entries.get(body.model_type.strip().lower())
    if entry is None:
        raise InvalidRequestError("当前任务类型不支持该模型转换")
    target = body.target
    options: dict[str, object] = {}
    if body.onnx_opset_version is not None:
        options["onnx_opset_version"] = body.onnx_opset_version
    options["input_shape_mode"] = body.input_shape_mode
    for key in ("int8_calibration", "int8_validation", "input_profile", "workspace_gib"):
        value = getattr(body, key)
        if value is not None:
            options[key] = value
    if target.startswith("openvino-ir-"):
        target_format = "openvino-ir"
        options["openvino_ir_precision"] = target.removeprefix("openvino-ir-")
    elif target.startswith("tensorrt-engine-"):
        target_format = "tensorrt-engine"
        options["tensorrt_engine_precision"] = target.removeprefix("tensorrt-engine-")
    else:
        target_format = target
    service_cls, request_cls = entry.resolve_types()
    request_args: dict[str, object] = {
        "project_id": body.project_id,
        "source_model_version_id": body.source_model_version_id,
        "target_formats": (target_format,),
        "runtime_profile_id": body.runtime_profile_id,
        "extra_options": options,
    }
    if entry.request_includes_task_type:
        request_args["task_type"] = task_type
    preview_options = {} if entry.request_includes_task_type else {"expected_task_type": task_type}
    preview = service_cls(session_factory=session_factory, dataset_storage=storage).preview_conversion_task(request_cls(**request_args), **preview_options)
    if preview.get("task_type") != task_type:
        raise InvalidRequestError("来源模型的任务类型与转换请求不一致")
    if body.onnx_opset_version is not None:
        preview["onnx_opset_version"] = body.onnx_opset_version
    preview["input_shape_mode"] = body.input_shape_mode
    return preview
