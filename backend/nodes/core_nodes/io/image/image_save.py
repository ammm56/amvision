"""图片保存节点。"""

from __future__ import annotations

from datetime import datetime

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.image_file_name_template import (
    image_media_type_for_file_name,
    render_image_file_name_template,
)
from backend.nodes.runtime_support import (
    build_storage_image_payload,
    infer_media_type_from_image_bytes,
    load_encoded_image_bytes_from_payload,
    require_image_payload,
)
from backend.nodes.save_locations import (
    SAVE_LOCATION_OBJECT_STORE,
    resolve_optional_save_location,
    save_bytes,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from backend.service.infrastructure.object_store.object_key_layout import (
    build_project_workflow_application_results_dir,
)


def _image_save_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按明确目录和文件名把图片保存到 ObjectStore 或系统绝对路径。"""

    overwrite = bool(request.parameters.get("overwrite", False))
    source_payload = require_image_payload(request.input_values.get("image"))
    current_time = datetime.now().astimezone()
    format_context = _build_image_save_format_context(
        request,
        current_time=current_time,
    )
    raw_save_directory = _resolve_save_directory_template(
        request,
        request.parameters.get("save_directory"),
        format_context=format_context,
    )
    save_location = resolve_optional_save_location(
        raw_save_directory,
        scope="directory",
    )
    if save_location is None:
        raise InvalidRequestError(
            "Image Save 保存目录不能为空",
            details={"node_id": request.node_id, "parameter_name": "save_directory"},
        )
    file_name = render_image_file_name_template(
        request.parameters.get("file_name"),
        current_time=current_time,
        context=format_context,
    )
    normalized_payload, image_bytes = load_encoded_image_bytes_from_payload(
        request,
        image_payload=source_payload,
        target_location=file_name,
    )
    expected_media_type = image_media_type_for_file_name(file_name)
    actual_media_type = infer_media_type_from_image_bytes(image_bytes)
    if actual_media_type != expected_media_type:
        raise InvalidRequestError(
            "Image Save 文件扩展名与图片编码不一致",
            details={
                "node_id": request.node_id,
                "file_name": file_name,
                "expected_media_type": expected_media_type,
                "actual_media_type": actual_media_type,
            },
        )
    saved_file = save_bytes(
        request,
        save_location=save_location,
        content=image_bytes,
        file_name=file_name,
        overwrite=overwrite,
        increment_on_conflict=not overwrite,
    )
    if saved_file.kind == SAVE_LOCATION_OBJECT_STORE:
        saved_payload = build_storage_image_payload(
            object_key=str(saved_file.object_key or ""),
            source_payload=normalized_payload,
            media_type=actual_media_type,
        )
    else:
        # 磁盘落图不改变后续节点的数据面，继续传递原始 image-ref。
        saved_payload = dict(source_payload)
    saved_payload["saved_output"] = saved_file.to_payload()
    return {"image": saved_payload}


def _resolve_save_directory_template(
    request: WorkflowNodeExecutionRequest,
    raw_save_directory: object,
    *,
    format_context: dict[str, str] | None = None,
) -> str | None:
    """解析 Image Save 保存目录中的 workflow 上下文占位符。"""

    if not isinstance(raw_save_directory, str) or not raw_save_directory.strip():
        return None

    normalized_save_directory = raw_save_directory.strip()
    try:
        return normalized_save_directory.format(
            **(format_context or _build_image_save_format_context(request))
        )
    except (KeyError, ValueError) as exc:
        placeholder = exc.args[0] if isinstance(exc, KeyError) and exc.args else None
        raise InvalidRequestError(
            "Image Save 保存目录模板不合法",
            details={"node_id": request.node_id, "placeholder": placeholder},
        ) from exc


def _build_image_save_format_context(
    request: WorkflowNodeExecutionRequest,
    *,
    current_time: datetime | None = None,
) -> dict[str, str]:
    """构建 Image Save 保存目录和文件名可用的占位符上下文。

    参数：
    - request：当前节点执行请求。

    返回：
    - dict[str, str]：可用于 format 的占位符映射。
    """

    workflow_run_id = str(
        request.execution_metadata.get("workflow_run_id") or "default-run"
    )
    context = {
        "workflow_run_id": workflow_run_id,
        "timestamp": (current_time or datetime.now().astimezone()).strftime(
            "%Y%m%dT%H%M%S%f%z"
        ),
        "node_id": request.node_id,
    }
    project_id = _read_optional_execution_metadata_text(request, key="project_id")
    if project_id is not None:
        context["project_id"] = project_id
    application_id = _read_optional_execution_metadata_text(
        request, key="application_id"
    )
    if application_id is not None:
        context["application_id"] = application_id
    if project_id is not None and application_id is not None:
        context["workflow_app_result_dir"] = (
            build_project_workflow_application_results_dir(
                project_id=project_id,
                application_id=application_id,
                workflow_run_id=workflow_run_id,
            )
        )
    return context


def _read_optional_execution_metadata_text(
    request: WorkflowNodeExecutionRequest,
    *,
    key: str,
) -> str | None:
    """读取 execution_metadata 中的可选文本字段。

    参数：
    - request：当前节点执行请求。
    - key：目标字段名称。

    返回：
    - str | None：规范化后的文本值；缺失或为空时返回 None。
    """

    raw_value = request.execution_metadata.get(key)
    if not isinstance(raw_value, str):
        return None
    normalized_value = raw_value.strip()
    return normalized_value or None


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.image-save",
        display_name="Save Image",
        category="core.io.image",
        description="按独立目录和文件名模板保存图片，并明确控制覆盖或自动编号。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "save_directory": {
                    "type": "string",
                    "title": "保存目录",
                    "description": "相对目录保存到 ObjectStore，绝对目录保存到 runtime 主机磁盘。",
                    "x-amvision-i18n": {
                        "title": {
                            "zh-CN": "保存目录",
                            "en-US": "Save directory",
                        },
                        "description": {
                            "zh-CN": "相对目录保存到 ObjectStore，绝对目录保存到 runtime 主机磁盘。",
                            "en-US": "A relative directory saves to ObjectStore; an absolute directory saves to the runtime host filesystem.",
                        },
                    },
                    "x-amvision-ui": {"order": 10},
                },
                "file_name": {
                    "type": "string",
                    "title": "文件名",
                    "description": "完整图片文件名；可使用 {YYYYMMDDhhmmssSSS} 时间格式，例如 tray_{YYYYMMDDhhmmssSSS}_OK.jpg。",
                    "x-amvision-i18n": {
                        "title": {
                            "zh-CN": "文件名",
                            "en-US": "File name",
                        },
                        "description": {
                            "zh-CN": "完整图片文件名；可使用 {YYYYMMDDhhmmssSSS} 时间格式，例如 tray_{YYYYMMDDhhmmssSSS}_OK.jpg。",
                            "en-US": "Complete image file name. A time block such as {YYYYMMDDhhmmssSSS} is optional.",
                        },
                    },
                    "x-amvision-ui": {"order": 20},
                },
                "overwrite": {
                    "type": "boolean",
                    "title": "覆盖已有文件",
                    "description": "启用时覆盖精确文件名；关闭时在重名文件后自动追加 _001、_002。",
                    "default": False,
                    "x-amvision-i18n": {
                        "title": {
                            "zh-CN": "覆盖已有文件",
                            "en-US": "Overwrite existing file",
                        },
                        "description": {
                            "zh-CN": "启用时覆盖精确文件名；关闭时在重名文件后自动追加 _001、_002。",
                            "en-US": "Overwrite the exact name when enabled; otherwise append _001, _002 on conflicts.",
                        },
                    },
                    "x-amvision-ui": {"order": 30},
                },
            },
            "required": ["save_directory", "file_name", "overwrite"],
        },
        capability_tags=("io.output", "image.persist"),
    ),
    handler=_image_save_handler,
)
