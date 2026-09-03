"""本地 UTF-8 文本保存节点。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import (
    build_value_payload,
    require_value_payload,
)
from backend.nodes.file_name_template import render_file_name_template
from backend.nodes.save_node_contracts import (
    build_save_target_input_ports,
    build_save_target_parameter_input_bindings,
    build_save_target_parameter_properties,
    build_save_target_required_parameters,
)
from backend.nodes.save_locations import (
    build_save_template_context,
    resolve_required_save_directory,
    resolve_save_location_path,
    save_bytes,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.io import (
    WriteJournal,
    acquire_path_write_locks,
    build_node_operation_id,
)
from backend.service.application.runtime.io.write_journal import sha256_bytes
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


SUPPORTED_MODES = {"overwrite", "append", "fail-if-exists"}
SUPPORTED_ENCODINGS = {"utf-8", "utf-8-sig"}


def _text_save_local_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """把字符串保存到 ObjectStore 相对位置或本机绝对路径。"""

    text_value = require_value_payload(
        request.input_values.get("value"),
        field_name="value",
    )["value"]
    if not isinstance(text_value, str):
        raise InvalidRequestError("Save Text 的 value.value 必须是字符串")
    mode = _require_choice(
        request.parameters.get("mode", "overwrite"),
        field_name="mode",
        supported_values=SUPPORTED_MODES,
    )
    encoding = _require_choice(
        request.parameters.get("encoding", "utf-8"),
        field_name="encoding",
        supported_values=SUPPORTED_ENCODINGS,
    )
    ensure_trailing_newline = request.parameters.get("ensure_trailing_newline", False)
    if not isinstance(ensure_trailing_newline, bool):
        raise InvalidRequestError("ensure_trailing_newline 必须是 boolean")
    normalized_text = (
        f"{text_value}\n"
        if ensure_trailing_newline and not text_value.endswith(("\n", "\r"))
        else text_value
    )

    current_time = datetime.now().astimezone()
    format_context = build_save_template_context(
        request,
        current_time=current_time,
    )
    rendered_directory, save_location = resolve_required_save_directory(
        request,
        request.parameters.get("save_directory"),
        node_label="Save Text",
        current_time=current_time,
        context=format_context,
    )
    file_name = render_file_name_template(
        request.parameters.get("file_name"),
        node_label="Save Text",
        current_time=current_time,
        context=format_context,
    )
    target_path, _ = resolve_save_location_path(
        request,
        save_location=save_location,
        file_name=file_name,
    )
    with acquire_path_write_locks(request, (target_path,)):
        target_exists = target_path.exists()
        if mode == "fail-if-exists" and target_exists:
            raise InvalidRequestError("Save Text 的保存目标已存在")
        existing_bytes = (
            target_path.read_bytes() if mode == "append" and target_exists else b""
        )
        append_encoding = (
            "utf-8" if existing_bytes and encoding == "utf-8-sig" else encoding
        )
        appended_bytes = normalized_text.encode(append_encoding)
        output_bytes = existing_bytes + appended_bytes
        idempotent_replay = False
        if mode == "append":
            idempotent_replay = _append_was_already_committed(
                request=request,
                target_path=target_path,
                appended_bytes=appended_bytes,
            )
            if not idempotent_replay:
                _prepare_text_append(
                    request=request,
                    target_path=target_path,
                    offset=len(existing_bytes),
                    appended_bytes=appended_bytes,
                )
        if not idempotent_replay:
            saved_file = save_bytes(
                request,
                save_location=save_location,
                content=output_bytes,
                file_name=file_name,
                overwrite=True,
            )
            if mode == "append":
                _commit_text_append(request=request, target_path=target_path)
        else:
            _, saved_file = resolve_save_location_path(
                request,
                save_location=save_location,
                file_name=file_name,
            )
    return {
        "summary": build_value_payload(
            {
                "saved_output": saved_file.to_payload(),
                "save_directory": rendered_directory,
                "file_name": file_name,
                "mode": mode,
                "encoding": encoding,
                "appended_size_bytes": len(appended_bytes),
                "total_size_bytes": target_path.stat().st_size,
                "idempotent_replay": idempotent_replay,
            }
        )
    }


def _append_was_already_committed(
    *,
    request: WorkflowNodeExecutionRequest,
    target_path: Path,
    appended_bytes: bytes,
) -> bool:
    """识别当前 invocation 已经写入的追加内容。"""

    journal = _text_append_journal(request=request, target_path=target_path)
    record = journal.load()
    if record is None:
        return False
    offset = _require_non_negative_int(record.get("offset"), field_name="offset")
    expected_length = _require_non_negative_int(
        record.get("payload_length"),
        field_name="payload_length",
    )
    expected_digest = record.get("payload_sha256")
    if expected_length != len(appended_bytes) or expected_digest != sha256_bytes(
        appended_bytes
    ):
        raise InvalidRequestError("Save Text 的幂等 journal 与当前追加内容不一致")
    path = journal.target_path
    if not path.is_file() or path.stat().st_size < offset + expected_length:
        if record.get("state") == "committed":
            raise InvalidRequestError("Save Text 已提交内容与目标文件不一致")
        return False
    with path.open("rb") as input_stream:
        input_stream.seek(offset)
        existing_bytes = input_stream.read(expected_length)
    if sha256_bytes(existing_bytes) != expected_digest:
        if record.get("state") == "committed":
            raise InvalidRequestError("Save Text 已提交内容与目标文件不一致")
        return False
    if record.get("state") != "committed":
        journal.mark_committed(record)
    return True


def _prepare_text_append(
    *,
    request: WorkflowNodeExecutionRequest,
    target_path: Path,
    offset: int,
    appended_bytes: bytes,
) -> None:
    """在原子替换前记录待追加字节。"""

    journal = _text_append_journal(request=request, target_path=target_path)
    existing_record = journal.load()
    if existing_record is not None and existing_record.get("state") == "committed":
        raise InvalidRequestError("Save Text 已提交 journal 不能重新准备")
    journal.write_prepared(
        {
            "offset": offset,
            "payload_length": len(appended_bytes),
            "payload_sha256": sha256_bytes(appended_bytes),
        }
    )


def _commit_text_append(
    *,
    request: WorkflowNodeExecutionRequest,
    target_path: Path,
) -> None:
    """标记当前追加操作已提交。"""

    journal = _text_append_journal(request=request, target_path=target_path)
    record = journal.load()
    if record is None:
        raise InvalidRequestError("Save Text 追加 journal 未创建")
    journal.mark_committed(record)


def _text_append_journal(
    *,
    request: WorkflowNodeExecutionRequest,
    target_path: Path,
) -> WriteJournal:
    """构造当前节点 invocation 的追加 journal。"""

    return WriteJournal(
        target_path=target_path,
        operation_id=build_node_operation_id(
            request,
            operation_kind="text-save-local-append",
        ),
        operation_kind="text-append",
    )


def _require_non_negative_int(value: object, *, field_name: str) -> int:
    """读取 journal 中的非负整数。"""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequestError(f"Save Text journal 的 {field_name} 无效")
    return value


def _require_choice(
    raw_value: object,
    *,
    field_name: str,
    supported_values: set[str],
) -> str:
    """读取受控小写枚举。"""

    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{field_name} 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in supported_values:
        raise InvalidRequestError(
            f"{field_name} 仅支持 {', '.join(sorted(supported_values))}"
        )
    return normalized_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.output.text-save-local",
        display_name="Save Text",
        category="core.io.file",
        description="以 UTF-8 保存文本，支持 ObjectStore 相对位置和本机绝对路径。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="value", display_name="Value", payload_type_id="value.v1"
            ),
            *build_save_target_input_ports(include_overwrite=False),
        ),
        output_ports=(
            NodePortDefinition(
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                **build_save_target_parameter_properties(
                    overwrite_default=None,
                    file_name_example=("log-{YYYY}-{MM}-{DD}-{hh}-{mm}-{ss}-{SSS}.txt"),
                ),
                "mode": {
                    "type": "string",
                    "enum": sorted(SUPPORTED_MODES),
                    "default": "overwrite",
                },
                "encoding": {
                    "type": "string",
                    "enum": sorted(SUPPORTED_ENCODINGS),
                    "default": "utf-8",
                },
                "ensure_trailing_newline": {
                    "type": "boolean",
                    "default": False,
                },
            },
            "required": build_save_target_required_parameters(
                include_overwrite=False,
            ),
        },
        parameter_input_bindings=build_save_target_parameter_input_bindings(
            include_overwrite=False,
        ),
        capability_tags=("io.output", "text.save", "storage.local"),
    ),
    handler=_text_save_local_handler,
)
