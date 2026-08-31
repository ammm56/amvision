"""workflow runtime multipart 请求构建。"""

from __future__ import annotations

import json
from pathlib import PurePath
from uuid import uuid4

from fastapi import Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from backend.contracts.workflows import FlowApplication
from backend.service.application.errors import InvalidRequestError, WorkflowInputError
from backend.service.application.workflows.execution_cleanup import (
    WORKFLOW_EXECUTION_CLEANUP_ITEMS_KEY,
    WORKFLOW_EXECUTION_CLEANUP_KIND_DATASET_STORAGE_TREE,
)
from backend.service.application.workflows.input_contracts import (
    DEFAULT_DATASET_PACKAGE_MAX_BYTES,
    DEFAULT_FILE_MAX_BYTES,
    WorkflowInputValidator,
)
from backend.service.application.workflows.runtime.invokes import (
    WorkflowRuntimeInvokeRequest,
)
from backend.service.domain.workflows.workflow_runtime_records import WorkflowAppRuntime

from .services import require_dataset_storage, with_created_by


_MULTIPART_RUNTIME_RESERVED_FIELDS = frozenset(
    {
        "input_bindings_json",
        "input_bindings",
        "execution_metadata_json",
        "execution_metadata",
        "timeout_seconds",
    }
)
_STREAMING_UPLOAD_PAYLOAD_TYPES = frozenset(
    {"image-ref.v1", "file-ref.v1", "file-refs.v1"}
)
# Starlette 对普通 multipart part 的默认上限是 1 MiB，无法承载公开契约允许的
# image-base64.v1。这里仅放宽 multipart 控制字段；文件 part 仍由每个 binding 的
# max_file_bytes 流式限制，解析后的 inline payload 仍由 App Contract 再次校验。
WORKFLOW_RUNTIME_MULTIPART_CONTROL_PART_MAX_BYTES = 160 * 1024 * 1024


async def build_multipart_runtime_invoke_request(
    *,
    request: Request,
    workflow_app_runtime: WorkflowAppRuntime,
    created_by: str,
) -> WorkflowRuntimeInvokeRequest:
    """把 multipart/form-data 确定性转换为统一 Workflow 输入。"""

    form = await request.form(
        max_part_size=WORKFLOW_RUNTIME_MULTIPART_CONTROL_PART_MAX_BYTES
    )
    dataset_storage = require_dataset_storage(request)
    upload_request_id = uuid4().hex
    upload_root = (
        f"workflows/runtime-inputs/{workflow_app_runtime.project_id}/"
        f"{workflow_app_runtime.workflow_runtime_id}/{upload_request_id}"
    )
    published_any = False
    try:
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
        application = load_runtime_application(
            request=request,
            workflow_app_runtime=workflow_app_runtime,
        )
        public_contract = load_runtime_public_contract(
            request=request,
            workflow_app_runtime=workflow_app_runtime,
        )
        contract_items = contract_input_index(public_contract)
        input_binding_payload_types = {
            binding.binding_id: str(
                binding.config.get("payload_type_id")
                or binding.metadata.get("payload_type_id")
                or ""
            )
            for binding in application.bindings
            if binding.direction == "input"
        }
        # v2 权威类型来自不可变 contract；旧 v1 才回退到 binding metadata。
        for binding_id, item in contract_items.items():
            payload_type_id = item.get("payload_type_id")
            if isinstance(payload_type_id, str):
                input_binding_payload_types[binding_id] = payload_type_id

        upload_groups: dict[str, list[UploadFile]] = {}
        for field_name, field_value in form.multi_items():
            if field_name in _MULTIPART_RUNTIME_RESERVED_FIELDS:
                continue
            if not isinstance(field_value, UploadFile):
                raise WorkflowInputError(
                    "multipart 非文件字段必须放入 input_bindings_json",
                    code="workflow_input_payload_schema_invalid",
                    details={"field_name": field_name},
                )
            upload_groups.setdefault(field_name, []).append(field_value)

        for binding_id in upload_groups:
            if binding_id in input_bindings:
                raise WorkflowInputError(
                    "multipart 文件字段与 input_bindings_json 冲突",
                    code="workflow_input_multipart_binding_conflict",
                    details={"binding_id": binding_id},
                )
            if binding_id not in input_binding_payload_types:
                raise WorkflowInputError(
                    "multipart 上传字段未声明为 Workflow 输入 binding",
                    code="workflow_input_unknown_binding",
                    details={"binding_ids": [binding_id]},
                )

        for binding_id, uploads in upload_groups.items():
            payload_type_id = input_binding_payload_types[binding_id]
            contract_item = contract_items.get(binding_id, {})
            if payload_type_id == "dataset-package.v1":
                if len(uploads) != 1:
                    raise_file_count(
                        binding_id=binding_id,
                        count=len(uploads),
                        maximum=1,
                    )
                input_bindings[
                    binding_id
                ] = await build_dataset_package_binding_payload(
                    upload=uploads[0],
                    binding_id=binding_id,
                    max_bytes=read_contract_limit(
                        contract_item.get("max_file_bytes"),
                        DEFAULT_DATASET_PACKAGE_MAX_BYTES,
                    ),
                )
                continue
            if payload_type_id not in _STREAMING_UPLOAD_PAYLOAD_TYPES:
                raise WorkflowInputError(
                    "当前 payload type 不支持 multipart 文件 transport",
                    code="workflow_input_payload_schema_invalid",
                    details={
                        "binding_id": binding_id,
                        "payload_type_id": payload_type_id,
                    },
                )
            maximum = (
                read_contract_limit(contract_item.get("max_files"), 64)
                if payload_type_id == "file-refs.v1"
                else 1
            )
            if len(uploads) > maximum:
                raise_file_count(
                    binding_id=binding_id,
                    count=len(uploads),
                    maximum=maximum,
                )
            file_payloads: list[dict[str, object]] = []
            for index, upload in enumerate(uploads):
                file_payloads.append(
                    await publish_workflow_upload(
                        dataset_storage=dataset_storage,
                        upload=upload,
                        binding_id=binding_id,
                        item_index=index,
                        payload_type_id=payload_type_id,
                        contract_item=contract_item,
                        upload_root=upload_root,
                    )
                )
                published_any = True
            input_bindings[binding_id] = (
                {"items": file_payloads, "count": len(file_payloads)}
                if payload_type_id == "file-refs.v1"
                else file_payloads[0]
            )

        WorkflowInputValidator(object_store=dataset_storage).validate(
            application=application,
            input_bindings=input_bindings,
            public_contract=public_contract,
            project_id=workflow_app_runtime.project_id,
        )
        if published_any:
            execution_metadata[WORKFLOW_EXECUTION_CLEANUP_ITEMS_KEY] = [
                {
                    "resource_kind": (
                        WORKFLOW_EXECUTION_CLEANUP_KIND_DATASET_STORAGE_TREE
                    ),
                    "resource_id": upload_root,
                    "metadata": {},
                }
            ]
        return WorkflowRuntimeInvokeRequest(
            input_bindings=input_bindings,
            execution_metadata=execution_metadata,
            timeout_seconds=timeout_seconds,
        )
    except WorkflowInputError:
        if published_any:
            dataset_storage.delete_tree(upload_root)
        raise
    except InvalidRequestError as exc:
        if published_any:
            dataset_storage.delete_tree(upload_root)
        if "超过大小限制" in exc.message:
            raise WorkflowInputError(
                "上传文件超过公开输入契约限制",
                code="workflow_input_file_size_exceeded",
                details=dict(exc.details),
            ) from exc
        raise
    except Exception as exc:
        if published_any:
            dataset_storage.delete_tree(upload_root)
        raise WorkflowInputError(
            "multipart 文件上传失败",
            code="workflow_input_upload_failed",
            details={"error_type": type(exc).__name__},
        ) from exc
    finally:
        await form.close()


async def publish_workflow_upload(
    *,
    dataset_storage: object,
    upload: UploadFile,
    binding_id: str,
    item_index: int,
    payload_type_id: str,
    contract_item: dict[str, object],
    upload_root: str,
) -> dict[str, object]:
    """把一个 UploadFile 流式原子发布，并生成规范引用 payload。"""

    file_name = require_safe_upload_file_name(
        upload.filename, binding_id=binding_id
    )
    media_type = (
        upload.content_type.strip().lower()
        if isinstance(upload.content_type, str) and upload.content_type.strip()
        else "application/octet-stream"
    )
    validate_upload_media_type(
        binding_id=binding_id,
        media_type=media_type,
        contract_item=contract_item,
    )
    max_file_bytes = read_contract_limit(
        contract_item.get("max_file_bytes"), DEFAULT_FILE_MAX_BYTES
    )
    try:
        receipt = await run_in_threadpool(
            dataset_storage.write_immutable_stream,
            object_prefix=f"{upload_root}/{binding_id}/{item_index}",
            source_stream=upload.file,
            media_type=media_type,
            extension=PurePath(file_name).suffix,
            max_bytes=max_file_bytes,
        )
    except InvalidRequestError as exc:
        if "超过大小限制" in exc.message:
            raise WorkflowInputError(
                "上传文件超过公开输入契约限制",
                code="workflow_input_file_size_exceeded",
                details={
                    "binding_id": binding_id,
                    "file_name": file_name,
                    "max_file_bytes": max_file_bytes,
                },
            ) from exc
        raise
    metadata = receipt.metadata
    if payload_type_id == "image-ref.v1":
        return {
            "transport_kind": "storage",
            "object_key": metadata.object_key,
            "media_type": metadata.media_type,
        }
    return {
        "transport_kind": "storage",
        "storage_ref": "object-store",
        "object_key": metadata.object_key,
        "file_name": file_name,
        "media_type": metadata.media_type,
        "content_length": metadata.content_length,
        "checksum_algorithm": metadata.checksum_algorithm,
        "checksum": metadata.checksum,
        "immutable_version": metadata.immutable_version,
    }


async def build_dataset_package_binding_payload(
    *,
    upload: UploadFile,
    binding_id: str,
    max_bytes: int = DEFAULT_DATASET_PACKAGE_MAX_BYTES,
) -> dict[str, object]:
    """构造 legacy dataset-package payload，并对读取大小设置硬上限。"""

    file_name = require_safe_upload_file_name(
        upload.filename, binding_id=binding_id
    )
    package_bytes = await upload.read(max_bytes + 1)
    if len(package_bytes) > max_bytes:
        raise WorkflowInputError(
            "上传数据集 zip 超过大小限制",
            code="workflow_input_file_size_exceeded",
            details={"binding_id": binding_id, "max_file_bytes": max_bytes},
        )
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
        payload["media_type"] = upload.content_type.strip().lower()
    return payload


def load_runtime_application(
    *,
    request: Request,
    workflow_app_runtime: WorkflowAppRuntime,
) -> FlowApplication:
    """读取指定 runtime revision 固定的不可变 FlowApplication 快照。"""

    application_payload = require_dataset_storage(request).read_json(
        workflow_app_runtime.application_snapshot_object_key
    )
    return FlowApplication.model_validate(application_payload)


def load_runtime_public_contract(
    *,
    request: Request,
    workflow_app_runtime: WorkflowAppRuntime,
) -> dict[str, object] | None:
    """读取 Runtime 固定的 App Contract；旧 Runtime 缺失时保持 v1 语义。"""

    object_key = workflow_app_runtime.metadata.get("contract_snapshot_object_key")
    if not isinstance(object_key, str) or not object_key.strip():
        return None
    payload = require_dataset_storage(request).read_json(object_key.strip())
    if not isinstance(payload, dict):
        raise InvalidRequestError("Workflow App contract snapshot 必须是对象")
    return dict(payload)


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


def contract_input_index(
    contract: dict[str, object] | None,
) -> dict[str, dict[str, object]]:
    """读取 App Contract 输入 binding 索引。"""

    if not isinstance(contract, dict) or not isinstance(contract.get("inputs"), list):
        return {}
    return {
        str(item["binding_id"]): dict(item)
        for item in contract["inputs"]
        if isinstance(item, dict) and isinstance(item.get("binding_id"), str)
    }


def require_safe_upload_file_name(value: object, *, binding_id: str) -> str:
    """只接受不含路径和控制字符的上传 basename。"""

    if not isinstance(value, str) or not value.strip():
        raise WorkflowInputError(
            "上传文件名不能为空",
            code="workflow_input_payload_schema_invalid",
            details={"binding_id": binding_id},
        )
    file_name = value.strip()
    if (
        file_name in {".", ".."}
        or "/" in file_name
        or "\\" in file_name
        or any(ord(character) < 32 for character in file_name)
    ):
        raise WorkflowInputError(
            "上传文件名必须是安全 basename",
            code="workflow_input_payload_schema_invalid",
            details={"binding_id": binding_id},
        )
    return file_name


def validate_upload_media_type(
    *,
    binding_id: str,
    media_type: str,
    contract_item: dict[str, object],
) -> None:
    """在写入前校验声明 MIME allowlist。"""

    allowed = contract_item.get("allowed_media_types")
    if not isinstance(allowed, list) or not allowed:
        return
    if any(_media_type_matches(media_type, str(pattern)) for pattern in allowed):
        return
    raise WorkflowInputError(
        "文件 media_type 不在公开输入契约允许范围内",
        code="workflow_input_file_media_type_rejected",
        details={
            "binding_id": binding_id,
            "media_type": media_type,
            "allowed_media_types": allowed,
        },
    )


def _media_type_matches(media_type: str, pattern: str) -> bool:
    """匹配精确 MIME 或 type/*。"""

    normalized = pattern.strip().lower()
    return (
        media_type.startswith(normalized[:-1])
        if normalized.endswith("/*")
        else media_type == normalized
    )


def read_contract_limit(value: object, fallback: int) -> int:
    """读取正整数限制，否则使用平台保守默认值。"""

    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return fallback


def raise_file_count(*, binding_id: str, count: int, maximum: int) -> None:
    """抛出稳定的文件数量错误。"""

    raise WorkflowInputError(
        "multipart 文件数量超过公开输入契约限制",
        code="workflow_input_file_count_exceeded",
        details={"binding_id": binding_id, "count": count, "max_files": maximum},
    )
