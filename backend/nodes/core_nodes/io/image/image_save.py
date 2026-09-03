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
from backend.nodes.save_node_contracts import (
    build_save_target_input_ports,
    build_save_target_parameter_input_bindings,
    build_save_target_parameter_properties,
    build_save_target_required_parameters,
    read_save_overwrite,
)
from backend.nodes.save_locations import (
    SAVE_LOCATION_OBJECT_STORE,
    build_save_template_context,
    resolve_required_save_directory,
    save_bytes,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _image_save_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按明确目录和文件名把图片保存到 ObjectStore 或系统绝对路径。"""

    overwrite = read_save_overwrite(
        request.parameters.get("overwrite"),
        node_label="Save Image",
    )
    source_payload = require_image_payload(request.input_values.get("image"))
    current_time = datetime.now().astimezone()
    format_context = build_save_template_context(
        request,
        current_time=current_time,
    )
    _, save_location = resolve_required_save_directory(
        request,
        request.parameters.get("save_directory"),
        node_label="Image Save",
        current_time=current_time,
        context=format_context,
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
            *build_save_target_input_ports(include_overwrite=True),
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
            "properties": build_save_target_parameter_properties(
                overwrite_default=False,
                file_name_example=(
                    "saveimage-{YYYY}-{MM}-{DD}-{hh}-{mm}-{ss}-{SSS}.jpg"
                ),
            ),
            "required": build_save_target_required_parameters(
                include_overwrite=True,
            ),
        },
        parameter_input_bindings=build_save_target_parameter_input_bindings(
            include_overwrite=True,
        ),
        capability_tags=("io.output", "image.persist"),
    ),
    handler=_image_save_handler,
)
