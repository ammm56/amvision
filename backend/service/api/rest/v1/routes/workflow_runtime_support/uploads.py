"""workflow runtime multipart 请求构建。"""

from __future__ import annotations

import json

from fastapi import Request
from starlette.datastructures import UploadFile

from backend.contracts.workflows import FlowApplication
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.runtime.invokes import WorkflowRuntimeInvokeRequest
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService
from backend.service.domain.workflows.workflow_runtime_records import WorkflowAppRuntime

from .services import require_dataset_storage, require_node_catalog_registry, with_created_by


_MULTIPART_RUNTIME_RESERVED_FIELDS = frozenset(
    {
        "input_bindings_json",
        "input_bindings",
        "execution_metadata_json",
        "execution_metadata",
        "timeout_seconds",
    }
)


async def build_multipart_runtime_invoke_request(
    *,
    request: Request,
    workflow_app_runtime: WorkflowAppRuntime,
    created_by: str,
) -> WorkflowRuntimeInvokeRequest:
    """把 multipart/form-data 请求转换为 workflow runtime 调用请求。"""

    form = await request.form()
    input_bindings = read_optional_json_object(
        form.get("input_bindings_json") or form.get("input_bindings"),
        field_name="input_bindings_json",
    )
    execution_metadata = with_created_by(
        read_optional_json_object(
            form.get("execution_metadata_json") or form.get("execution_metadata"),
            field_name="execution_metadata_json",
        ),
        created_by,
    )
    timeout_seconds = read_optional_int_text(
        form.get("timeout_seconds"),
        field_name="timeout_seconds",
    )
    application = load_runtime_application(request=request, workflow_app_runtime=workflow_app_runtime)
    input_binding_payload_types = {
        binding.binding_id: str(
            binding.config.get("payload_type_id")
            or binding.metadata.get("payload_type_id")
            or ""
        )
        for binding in application.bindings
        if binding.direction == "input"
    }
    for field_name, field_value in form.multi_items():
        if field_name in _MULTIPART_RUNTIME_RESERVED_FIELDS:
            continue
        if isinstance(field_value, UploadFile):
            if field_name in input_bindings:
                raise InvalidRequestError(
                    "multipart 上传字段与 input_bindings_json 中的 binding_id 冲突",
                    details={"binding_id": field_name},
                )
            payload_type_id = input_binding_payload_types.get(field_name)
            if payload_type_id is None:
                raise InvalidRequestError(
                    "multipart 上传字段未声明为 workflow application 输入绑定",
                    details={"binding_id": field_name},
                )
            if payload_type_id != "dataset-package.v1":
                raise InvalidRequestError(
                    "当前 multipart 上传入口仅支持 dataset-package.v1 输入绑定",
                    details={"binding_id": field_name, "payload_type_id": payload_type_id},
                )
            input_bindings[field_name] = await build_dataset_package_binding_payload(
                upload=field_value,
                binding_id=field_name,
            )
            continue
        raise InvalidRequestError(
            "multipart 非文件字段请放入 input_bindings_json 或 execution_metadata_json",
            details={"field_name": field_name},
        )
    return WorkflowRuntimeInvokeRequest(
        input_bindings=input_bindings,
        execution_metadata=execution_metadata,
        timeout_seconds=timeout_seconds,
    )


async def build_dataset_package_binding_payload(
    *,
    upload: UploadFile,
    binding_id: str,
) -> dict[str, object]:
    """把上传文件转换为 DatasetImport 节点消费的 payload。"""

    package_bytes = await upload.read()
    file_name = upload.filename.strip() if isinstance(upload.filename, str) and upload.filename.strip() else "dataset.zip"
    if not package_bytes:
        raise InvalidRequestError(
            "上传数据集 zip 不能为空",
            details={"binding_id": binding_id, "file_name": file_name},
        )
    payload: dict[str, object] = {
        "package_file_name": file_name,
        "package_bytes": package_bytes,
    }
    if isinstance(upload.content_type, str) and upload.content_type.strip():
        payload["media_type"] = upload.content_type.strip()
    return payload


def load_runtime_application(
    *,
    request: Request,
    workflow_app_runtime: WorkflowAppRuntime,
) -> FlowApplication:
    """读取指定 runtime 绑定的 FlowApplication。"""

    workflow_service = LocalWorkflowJsonService(
        dataset_storage=require_dataset_storage(request),
        node_catalog_registry=require_node_catalog_registry(request),
    )
    return workflow_service.get_application(
        project_id=workflow_app_runtime.project_id,
        application_id=workflow_app_runtime.application_id,
    ).application


def read_optional_json_object(value: object, *, field_name: str) -> dict[str, object]:
    """把可选的 JSON 文本字段解析为对象。"""

    if value is None:
        return {}
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(
            "multipart JSON 字段必须是非空字符串",
            details={"field_name": field_name},
        )
    try:
        parsed_value = json.loads(value)
    except json.JSONDecodeError as exc:
        raise InvalidRequestError(
            "multipart JSON 字段不是有效 JSON",
            details={"field_name": field_name},
        ) from exc
    if not isinstance(parsed_value, dict):
        raise InvalidRequestError(
            "multipart JSON 字段必须是对象",
            details={"field_name": field_name},
        )
    return {str(key): item for key, item in parsed_value.items()}


def read_optional_int_text(value: object, *, field_name: str) -> int | None:
    """把可选字符串字段解析为整数。"""

    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(
            "multipart 整数字段必须是非空字符串",
            details={"field_name": field_name},
        )
    try:
        normalized_value = int(value.strip())
    except ValueError as exc:
        raise InvalidRequestError(
            "multipart 整数字段不是有效整数",
            details={"field_name": field_name},
        ) from exc
    return normalized_value
