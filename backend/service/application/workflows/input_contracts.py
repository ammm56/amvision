"""Workflow App v1 公开输入契约构建与统一校验。"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import PurePosixPath
from typing import Final

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from backend.contracts.workflows.workflow_graph import (
    FLOW_BINDING_DIRECTION_INPUT,
    FlowApplication,
    FlowApplicationBinding,
    WorkflowGraphTemplate,
    WorkflowPayloadContract,
)
from backend.nodes.core_nodes.support.file_payloads import (
    require_file_ref_payload,
    require_file_refs_payload,
)
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.errors import (
    ServiceConfigurationError,
    WorkflowInputError,
)
from backend.service.application.ports.object_store import ObjectStore


WORKFLOW_APP_CONTRACT_FORMAT: Final = "amvision.workflow-app-contract.v1"
DEFAULT_INLINE_MAX_BYTES: Final = 1024 * 1024
DEFAULT_IMAGE_BASE64_MAX_BYTES: Final = 128 * 1024 * 1024
DEFAULT_FILE_MAX_BYTES: Final = 512 * 1024 * 1024
DEFAULT_DATASET_PACKAGE_MAX_BYTES: Final = 20 * 1024 * 1024 * 1024
DEFAULT_FILES_MAX_COUNT: Final = 64


class WorkflowInputValidator:
    """对所有 Workflow 调用入口执行同一份公开输入校验。"""

    def __init__(self, *, object_store: ObjectStore | None = None) -> None:
        """保存可选 ObjectStore；提供后验证文件不可变 identity。"""

        self.object_store = object_store

    def validate(
        self,
        *,
        application: FlowApplication,
        input_bindings: dict[str, object],
        public_contract: dict[str, object] | None = None,
        allowed_template_input_ids: set[str] | None = None,
        project_id: str | None = None,
    ) -> dict[str, object]:
        """校验 binding 集合、schema、限制与对象 identity。"""

        declared_bindings = {
            binding.binding_id: binding
            for binding in application.bindings
            if binding.direction == FLOW_BINDING_DIRECTION_INPUT
        }
        active_bindings = {
            binding_id: binding
            for binding_id, binding in declared_bindings.items()
            if allowed_template_input_ids is None
            or binding.template_port_id in allowed_template_input_ids
        }
        unknown_binding_ids = sorted(set(input_bindings) - set(declared_bindings))
        if unknown_binding_ids:
            raise WorkflowInputError(
                "workflow application 收到未声明的输入绑定",
                code="workflow_input_unknown_binding",
                details={"binding_ids": unknown_binding_ids},
            )
        missing_binding_ids = sorted(
            binding_id
            for binding_id, binding in active_bindings.items()
            if binding.required and binding_id not in input_bindings
        )
        if missing_binding_ids:
            raise WorkflowInputError(
                "workflow application 缺少必需输入绑定",
                code="workflow_input_required_binding_missing",
                details={"binding_ids": missing_binding_ids},
            )
        if public_contract is None:
            return dict(input_bindings)
        if public_contract.get("format_id") != WORKFLOW_APP_CONTRACT_FORMAT:
            raise WorkflowInputError(
                "Workflow App 公开契约格式无效",
                code="workflow_input_contract_format_invalid",
                details={"format_id": public_contract.get("format_id")},
            )

        contract_items = _contract_item_index(public_contract.get("inputs"))
        for binding_id, payload in input_bindings.items():
            contract_item = contract_items.get(binding_id)
            if contract_item is None:
                raise WorkflowInputError(
                    "Workflow App 公开契约缺少输入 binding",
                    code="workflow_input_unknown_binding",
                    details={"binding_ids": [binding_id]},
                )
            self._validate_payload_schema(
                binding_id=binding_id,
                payload=payload,
                contract_item=contract_item,
            )
            self._validate_request_schema(
                binding_id=binding_id,
                payload=payload,
                contract_item=contract_item,
            )
            self._validate_inline_size(
                binding_id=binding_id,
                payload=payload,
                contract_item=contract_item,
            )
            self._validate_media_type(
                binding_id=binding_id,
                payload=payload,
                contract_item=contract_item,
            )
            payload_type_id = str(contract_item.get("payload_type_id") or "")
            if (
                payload_type_id == "image-ref.v1"
                and isinstance(payload, dict)
                and payload.get("transport_kind") == "storage"
            ):
                self._validate_storage_image_ref(
                    binding_id=binding_id,
                    payload=payload,
                    project_id=project_id,
                )
            elif payload_type_id == "file-ref.v1":
                file_ref = require_file_ref_payload(payload, field_name=binding_id)
                self._validate_file_ref(
                    binding_id=binding_id,
                    file_ref=file_ref,
                    contract_item=contract_item,
                    project_id=project_id,
                )
            elif payload_type_id == "file-refs.v1":
                file_refs = require_file_refs_payload(payload, field_name=binding_id)
                max_files = _read_positive_int(contract_item.get("max_files"))
                if max_files is not None and int(file_refs["count"]) > max_files:
                    raise WorkflowInputError(
                        "上传文件数量超过公开输入契约限制",
                        code="workflow_input_file_count_exceeded",
                        details={
                            "binding_id": binding_id,
                            "count": file_refs["count"],
                            "max_files": max_files,
                        },
                    )
                for file_ref in file_refs["items"]:
                    self._validate_file_ref(
                        binding_id=binding_id,
                        file_ref=file_ref,
                        contract_item=contract_item,
                        project_id=project_id,
                    )
        return dict(input_bindings)

    def _validate_storage_image_ref(
        self,
        *,
        binding_id: str,
        payload: dict[str, object],
        project_id: str | None,
    ) -> None:
        """校验 storage 图片引用的 Project scope 和不可变存储属性。"""

        object_key = payload.get("object_key")
        if not isinstance(object_key, str) or not object_key.strip():
            return
        object_key = object_key.strip()
        if project_id is not None and not _object_key_belongs_to_project(
            object_key=object_key,
            project_id=project_id,
        ):
            raise WorkflowInputError(
                "图片 ObjectStore 引用不属于当前 Project",
                code="workflow_input_object_reference_invalid",
                details={"binding_id": binding_id, "object_key": object_key},
            )
        if self.object_store is None:
            return
        try:
            metadata = self.object_store.stat_object(object_key)
        except Exception as exc:
            raise WorkflowInputError(
                "图片 ObjectStore 引用不存在或不可读取",
                code="workflow_input_object_reference_invalid",
                details={"binding_id": binding_id, "object_key": object_key},
            ) from exc
        if not metadata.is_immutable:
            raise WorkflowInputError(
                "图片 ObjectStore 引用不是不可变对象",
                code="workflow_input_object_reference_invalid",
                details={"binding_id": binding_id, "object_key": object_key},
            )

    @staticmethod
    def _validate_payload_schema(
        *,
        binding_id: str,
        payload: object,
        contract_item: dict[str, object],
    ) -> None:
        """按冻结的 Draft 2020-12 JSON Schema 校验单个 payload。"""

        schema = contract_item.get("payload_schema")
        if not isinstance(schema, dict):
            raise ServiceConfigurationError(
                "Workflow App 输入契约缺少 payload_schema",
                details={"binding_id": binding_id},
            )
        try:
            validator = Draft202012Validator(schema)
            schema_instance = _normalize_binary_schema_instance(payload, schema)
            errors = sorted(
                validator.iter_errors(schema_instance),
                key=lambda item: list(item.path),
            )
        except SchemaError as exc:
            raise ServiceConfigurationError(
                "Workflow App payload_schema 无效",
                details={"binding_id": binding_id},
            ) from exc
        if not errors:
            return
        error: ValidationError = errors[0]
        raise WorkflowInputError(
            "Workflow 输入 payload 不符合公开 schema",
            code="workflow_input_payload_schema_invalid",
            details={
                "binding_id": binding_id,
                "payload_path": [str(item) for item in error.absolute_path],
                "schema_path": [str(item) for item in error.absolute_schema_path],
                "reason": error.message,
            },
        )

    @staticmethod
    def _validate_request_schema(
        *,
        binding_id: str,
        payload: object,
        contract_item: dict[str, object],
    ) -> None:
        """对 value.v1 的 value 应用 binding 显式 request_schema。"""

        request_schema = contract_item.get("request_schema")
        if not isinstance(request_schema, dict) or not request_schema:
            return
        if not isinstance(payload, dict) or "value" not in payload:
            return
        try:
            validator = Draft202012Validator(request_schema)
            errors = sorted(
                validator.iter_errors(payload["value"]),
                key=lambda item: list(item.path),
            )
        except SchemaError as exc:
            raise ServiceConfigurationError(
                "Workflow App request_schema 无效",
                details={"binding_id": binding_id},
            ) from exc
        if not errors:
            return
        error = errors[0]
        raise WorkflowInputError(
            "Workflow 结构化输入不符合 binding request_schema",
            code="workflow_input_payload_schema_invalid",
            details={
                "binding_id": binding_id,
                "payload_path": [
                    "value",
                    *[str(item) for item in error.absolute_path],
                ],
                "schema_path": [str(item) for item in error.absolute_schema_path],
                "reason": error.message,
            },
        )

    @staticmethod
    def _validate_inline_size(
        *,
        binding_id: str,
        payload: object,
        contract_item: dict[str, object],
    ) -> None:
        """限制 JSON transport 的规范化字节大小。"""

        max_inline_bytes = _read_positive_int(contract_item.get("max_inline_bytes"))
        if max_inline_bytes is None:
            return
        encoded_length = len(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
        if encoded_length > max_inline_bytes:
            raise WorkflowInputError(
                "Workflow inline 输入超过公开契约限制",
                code="workflow_input_payload_schema_invalid",
                details={
                    "binding_id": binding_id,
                    "content_length": encoded_length,
                    "max_inline_bytes": max_inline_bytes,
                },
            )

    @staticmethod
    def _validate_media_type(
        *,
        binding_id: str,
        payload: object,
        contract_item: dict[str, object],
    ) -> None:
        """按精确值或 type/* 规则检查 payload media_type。"""

        allowed = contract_item.get("allowed_media_types")
        if (
            not isinstance(allowed, list)
            or not allowed
            or not isinstance(payload, dict)
        ):
            return
        media_type = payload.get("media_type")
        if not isinstance(media_type, str):
            return
        normalized = media_type.strip().lower()
        if any(_media_type_matches(normalized, str(pattern)) for pattern in allowed):
            return
        raise WorkflowInputError(
            "文件 media_type 不在公开输入契约允许范围内",
            code="workflow_input_file_media_type_rejected",
            details={
                "binding_id": binding_id,
                "media_type": normalized,
                "allowed_media_types": allowed,
            },
        )

    def _validate_file_ref(
        self,
        *,
        binding_id: str,
        file_ref: dict[str, object],
        contract_item: dict[str, object],
        project_id: str | None,
    ) -> None:
        """校验文件大小、Project scope 和 ObjectStore 不可变 identity。"""

        max_file_bytes = _read_positive_int(contract_item.get("max_file_bytes"))
        content_length = int(file_ref["content_length"])
        if max_file_bytes is not None and content_length > max_file_bytes:
            raise WorkflowInputError(
                "上传文件超过公开输入契约限制",
                code="workflow_input_file_size_exceeded",
                details={
                    "binding_id": binding_id,
                    "content_length": content_length,
                    "max_file_bytes": max_file_bytes,
                },
            )
        object_key = str(file_ref["object_key"])
        if project_id is not None and not _object_key_belongs_to_project(
            object_key=object_key,
            project_id=project_id,
        ):
            raise WorkflowInputError(
                "文件 ObjectStore 引用不属于当前 Project",
                code="workflow_input_object_reference_invalid",
                details={"binding_id": binding_id, "object_key": object_key},
            )
        if self.object_store is None:
            return
        try:
            metadata = self.object_store.stat_object(object_key)
        except Exception as exc:
            raise WorkflowInputError(
                "文件 ObjectStore 引用不存在或不可读取",
                code="workflow_input_object_reference_invalid",
                details={"binding_id": binding_id, "object_key": object_key},
            ) from exc
        if (
            not metadata.is_immutable
            or metadata.content_length != content_length
            or metadata.checksum_algorithm != file_ref["checksum_algorithm"]
            or metadata.checksum != file_ref["checksum"]
            or metadata.immutable_version != file_ref["immutable_version"]
        ):
            raise WorkflowInputError(
                "文件 ObjectStore 不可变 identity 与 payload 不一致",
                code="workflow_input_object_reference_invalid",
                details={"binding_id": binding_id, "object_key": object_key},
            )


def build_workflow_app_public_contract(
    *,
    application: FlowApplication,
    template: WorkflowGraphTemplate,
    node_catalog_registry: NodeCatalogRegistry,
) -> dict[str, object]:
    """冻结 payload schema、transport 和显式限制，生成 App Contract v1。"""

    payload_index = {
        item.payload_type_id: item
        for item in node_catalog_registry.get_workflow_payload_contracts()
    }
    input_index = {item.input_id: item for item in template.template_inputs}
    output_index = {item.output_id: item for item in template.template_outputs}
    inputs: list[dict[str, object]] = []
    outputs: list[dict[str, object]] = []
    for binding in sorted(application.bindings, key=lambda item: item.binding_id):
        if binding.direction == "input":
            target = input_index.get(binding.template_port_id)
            if target is None:
                continue
            payload_contract = _require_payload_contract(
                payload_index, target.payload_type_id
            )
            inputs.append(_build_input_contract_item(binding, payload_contract))
            continue
        source = output_index.get(binding.template_port_id)
        if source is None:
            continue
        payload_contract = _require_payload_contract(
            payload_index, source.payload_type_id
        )
        outputs.append(
            {
                **_binding_contract_fields(binding, source.payload_type_id),
                "payload_schema": _closed_outer_schema(payload_contract.json_schema),
            }
        )
    return {
        "format_id": WORKFLOW_APP_CONTRACT_FORMAT,
        "application_id": application.application_id,
        "inputs": inputs,
        "outputs": outputs,
    }


def normalize_contract_for_compatibility(
    contract: dict[str, object],
) -> dict[str, object]:
    """把公开契约映射到稳定的兼容性比较 profile。"""
    normalized = {
        "application_id": contract.get("application_id"),
        "inputs": [],
        "outputs": [],
    }
    for direction in ("inputs", "outputs"):
        items = contract.get(direction)
        if not isinstance(items, list):
            continue
        normalized[direction] = [
            {
                key: item.get(key)
                for key in (
                    "binding_id",
                    "template_port_id",
                    "payload_type_id",
                    "binding_kind",
                    "required",
                    "config",
                )
            }
            for item in items
            if isinstance(item, dict)
        ]
    return normalized


def find_workflow_app_public_contract_issues(
    contract: object,
) -> tuple[dict[str, object], ...]:
    """返回不满足当前 Workflow App v1 公开契约定义的问题。"""

    if not isinstance(contract, dict):
        return ({"kind": "contract_not_object"},)

    issues: list[dict[str, object]] = []
    if contract.get("format_id") != WORKFLOW_APP_CONTRACT_FORMAT:
        issues.append(
            {
                "kind": "format_invalid",
                "format_id": contract.get("format_id"),
                "required_format_id": WORKFLOW_APP_CONTRACT_FORMAT,
            }
        )
    for direction in ("inputs", "outputs"):
        items = contract.get(direction)
        if not isinstance(items, list):
            issues.append({"kind": "bindings_invalid", "direction": direction})
            continue
        seen_binding_ids: set[str] = set()
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                issues.append(
                    {
                        "kind": "binding_invalid",
                        "direction": direction,
                        "index": index,
                    }
                )
                continue
            binding_id = item.get("binding_id")
            if not isinstance(binding_id, str) or not binding_id.strip():
                issues.append(
                    {
                        "kind": "binding_id_invalid",
                        "direction": direction,
                        "index": index,
                    }
                )
            elif binding_id in seen_binding_ids:
                issues.append(
                    {
                        "kind": "binding_id_duplicate",
                        "direction": direction,
                        "binding_id": binding_id,
                    }
                )
            else:
                seen_binding_ids.add(binding_id)
            if not isinstance(item.get("payload_schema"), dict):
                issues.append(
                    {
                        "kind": "payload_schema_missing",
                        "direction": direction,
                        "binding_id": binding_id,
                    }
                )
            if direction == "inputs":
                transports = item.get("transports")
                if not isinstance(transports, list) or not transports or any(
                    not isinstance(value, str) or not value.strip()
                    for value in transports
                ):
                    issues.append(
                        {
                            "kind": "transports_invalid",
                            "direction": direction,
                            "binding_id": binding_id,
                        }
                    )
    return tuple(issues)


def _build_input_contract_item(
    binding: FlowApplicationBinding,
    payload_contract: WorkflowPayloadContract,
) -> dict[str, object]:
    """构建一个包含显式 request 限制的输入 binding。"""

    payload_type_id = payload_contract.payload_type_id
    defaults = _request_defaults(payload_type_id, payload_contract.transport_kind)
    config = dict(binding.config)
    request_schema = config.get("request_schema")
    allowed_media_types = config.get(
        "allowed_media_types", defaults["allowed_media_types"]
    )
    if not isinstance(allowed_media_types, list):
        raise ServiceConfigurationError(
            "Workflow App binding.allowed_media_types 必须是数组",
            details={"binding_id": binding.binding_id},
        )
    return {
        **_binding_contract_fields(binding, payload_type_id),
        "payload_schema": _closed_outer_schema(payload_contract.json_schema),
        "request_schema": deepcopy(request_schema)
        if isinstance(request_schema, dict)
        else {},
        "allowed_media_types": [
            str(item).strip().lower() for item in allowed_media_types
        ],
        "max_inline_bytes": config.get(
            "max_inline_bytes", defaults["max_inline_bytes"]
        ),
        "max_file_bytes": config.get("max_file_bytes", defaults["max_file_bytes"]),
        "max_files": config.get("max_files", defaults["max_files"]),
        "transports": list(config.get("transports", defaults["transports"])),
        "charset": config.get("charset", defaults["charset"]),
    }


def _request_defaults(payload_type_id: str, transport_kind: str) -> dict[str, object]:
    """返回稳定且适合现有大图输入的默认 transport 限制。"""

    result: dict[str, object] = {
        "allowed_media_types": [],
        "max_inline_bytes": None,
        "max_file_bytes": None,
        "max_files": None,
        "transports": [transport_kind],
        "charset": None,
    }
    if payload_type_id == "image-base64.v1":
        result.update(
            allowed_media_types=["image/*"],
            max_inline_bytes=DEFAULT_IMAGE_BASE64_MAX_BYTES,
            transports=["json"],
        )
    elif payload_type_id == "image-ref.v1":
        result.update(
            allowed_media_types=["image/*"],
            max_inline_bytes=DEFAULT_INLINE_MAX_BYTES,
            max_file_bytes=DEFAULT_FILE_MAX_BYTES,
            max_files=1,
            transports=["json-reference", "multipart-upload"],
        )
    elif payload_type_id == "text.v1":
        result.update(
            allowed_media_types=["text/*", "application/json"],
            max_inline_bytes=DEFAULT_INLINE_MAX_BYTES,
            transports=["json"],
            charset="utf-8",
        )
    elif payload_type_id == "file-ref.v1":
        result.update(
            max_inline_bytes=DEFAULT_INLINE_MAX_BYTES,
            max_file_bytes=DEFAULT_FILE_MAX_BYTES,
            max_files=1,
            transports=["json-reference", "multipart-upload"],
        )
    elif payload_type_id == "file-refs.v1":
        result.update(
            max_inline_bytes=DEFAULT_INLINE_MAX_BYTES,
            max_file_bytes=DEFAULT_FILE_MAX_BYTES,
            max_files=DEFAULT_FILES_MAX_COUNT,
            transports=["json-reference", "multipart-upload"],
        )
    elif payload_type_id == "dataset-package.v1":
        result.update(
            allowed_media_types=["application/zip", "application/x-zip-compressed"],
            max_file_bytes=DEFAULT_DATASET_PACKAGE_MAX_BYTES,
            max_files=1,
            transports=["multipart-upload"],
        )
    elif transport_kind == "inline-json":
        result.update(max_inline_bytes=DEFAULT_INLINE_MAX_BYTES, transports=["json"])
    return result


def _binding_contract_fields(
    binding: FlowApplicationBinding,
    payload_type_id: str,
) -> dict[str, object]:
    """返回公开 binding identity 字段。"""

    return {
        "binding_id": binding.binding_id,
        "template_port_id": binding.template_port_id,
        "payload_type_id": payload_type_id,
        "binding_kind": binding.binding_kind,
        "required": binding.required,
        "config": binding.config,
    }


def _closed_outer_schema(schema: dict[str, object]) -> dict[str, object]:
    """复制 schema，并只关闭公开 payload 最外层对象。"""

    result = deepcopy(schema)
    if result.get("type") == "object":
        result["additionalProperties"] = False
    return result


def _require_payload_contract(
    index: dict[str, WorkflowPayloadContract],
    payload_type_id: str,
) -> WorkflowPayloadContract:
    """读取公开端口引用的 payload contract。"""

    contract = index.get(payload_type_id)
    if contract is None:
        raise ServiceConfigurationError(
            "Workflow App 公开端口引用了未注册 payload type",
            details={"payload_type_id": payload_type_id},
        )
    return contract


def _contract_item_index(value: object) -> dict[str, dict[str, object]]:
    """把公开 binding 数组转换为 id 索引。"""

    if not isinstance(value, list):
        return {}
    return {
        str(item["binding_id"]): dict(item)
        for item in value
        if isinstance(item, dict) and isinstance(item.get("binding_id"), str)
    }


def _read_positive_int(value: object) -> int | None:
    """读取可选正整数限制。"""

    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _media_type_matches(media_type: str, pattern: str) -> bool:
    """匹配精确 MIME 或 type/*。"""

    normalized_pattern = pattern.strip().lower()
    if normalized_pattern.endswith("/*"):
        return media_type.startswith(normalized_pattern[:-1])
    return media_type == normalized_pattern


def _object_key_belongs_to_project(*, object_key: str, project_id: str) -> bool:
    """验证通用文件引用位于当前 Project 的受控 ObjectStore 前缀。"""

    path = PurePosixPath(object_key)
    if path.is_absolute() or ".." in path.parts:
        return False
    normalized_project_id = project_id.strip()
    allowed_prefixes = (
        ("projects", normalized_project_id),
        ("workflows", "projects", normalized_project_id),
        ("workflows", "runtime-inputs", normalized_project_id),
    )
    return any(path.parts[: len(prefix)] == prefix for prefix in allowed_prefixes)


def _normalize_binary_schema_instance(value: object, schema: object) -> object:
    """把 Python bytes 映射为 JSON Schema binary string transport 表示。"""

    if isinstance(schema, dict) and schema.get("format") == "binary":
        return (
            "<binary>" if isinstance(value, bytes | bytearray | memoryview) else value
        )
    if isinstance(value, dict) and isinstance(schema, dict):
        properties = schema.get("properties")
        property_schemas = properties if isinstance(properties, dict) else {}
        return {
            key: _normalize_binary_schema_instance(item, property_schemas.get(key))
            for key, item in value.items()
        }
    if isinstance(value, list) and isinstance(schema, dict):
        item_schema = schema.get("items")
        return [_normalize_binary_schema_instance(item, item_schema) for item in value]
    return value


__all__ = [
    "DEFAULT_DATASET_PACKAGE_MAX_BYTES",
    "DEFAULT_FILE_MAX_BYTES",
    "WORKFLOW_APP_CONTRACT_FORMAT",
    "WorkflowInputValidator",
    "build_workflow_app_public_contract",
    "find_workflow_app_public_contract_issues",
    "normalize_contract_for_compatibility",
]
