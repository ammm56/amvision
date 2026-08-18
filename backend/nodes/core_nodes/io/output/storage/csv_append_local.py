"""本地 CSV 结果追加节点。"""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.local_io import (
    flatten_mapping_for_csv,
    resolve_value_or_result_input,
)
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.service import get_optional_str_tuple_parameter
from backend.nodes.save_locations import (
    resolve_required_save_location_from_request,
    resolve_save_location_path,
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


def _csv_append_local_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """把结果对象、报警对象或 value 追加到 ObjectStore 或系统 CSV 文件。"""

    save_location = resolve_required_save_location_from_request(
        request,
        scope="file",
    )
    output_path, saved_file = resolve_save_location_path(
        request, save_location=save_location
    )
    payload_value, record_kind = resolve_value_or_result_input(request)
    row = flatten_mapping_for_csv(payload_value)
    field_order = _read_field_order(request)
    with acquire_path_write_locks(request, (output_path,)):
        fieldnames, write_header, idempotent_replay = _append_csv_row(
            request=request,
            output_path=output_path,
            row=row,
            field_order=field_order,
        )
    return {
        "summary": build_value_payload(
            {
                "saved_output": saved_file.to_payload(),
                "file_name": output_path.name,
                "size_bytes": output_path.stat().st_size,
                "record_kind": record_kind,
                "field_count": len(fieldnames),
                "fieldnames": list(fieldnames),
                "wrote_header": write_header,
                "idempotent_replay": idempotent_replay,
            }
        )
    }


def _append_csv_row(
    *,
    request: WorkflowNodeExecutionRequest,
    output_path: Path,
    row: dict[str, str],
    field_order: tuple[str, ...] | None,
) -> tuple[list[str], bool, bool]:
    """在路径锁内使用 WAL 幂等追加一行 CSV。"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames, write_header = _resolve_fieldnames(
        output_path=output_path,
        row=row,
        field_order=field_order,
    )
    payload = _render_csv_append_bytes(
        fieldnames=fieldnames,
        row=row,
        write_header=write_header,
    )
    operation_id = build_node_operation_id(
        request,
        operation_kind="csv-append-local",
    )
    journal = WriteJournal(
        target_path=output_path,
        operation_id=operation_id,
        operation_kind="csv-append",
    )
    record = journal.load()
    if record is None:
        offset = output_path.stat().st_size if output_path.exists() else 0
        record = journal.write_prepared(
            {
                "offset": offset,
                "payload_length": len(payload),
                "payload_sha256": sha256_bytes(payload),
                "fieldnames": list(fieldnames),
                "wrote_header": write_header,
            }
        )
    record_fieldnames = record.get("fieldnames")
    if not isinstance(record_fieldnames, list):
        raise InvalidRequestError("CSV 追加 journal 缺少 fieldnames")
    resolved_fieldnames = [str(value) for value in record_fieldnames]
    resolved_write_header = record.get("wrote_header") is True
    if _journal_payload_matches(output_path, record):
        if record.get("state") != "committed":
            journal.mark_committed(record)
        return resolved_fieldnames, resolved_write_header, True
    if record.get("state") == "committed":
        raise InvalidRequestError(
            "CSV 已提交内容与幂等 journal 不一致",
            details={"local_path": str(output_path), "operation_id": operation_id},
        )
    offset = _require_non_negative_int(record.get("offset"), field_name="offset")
    current_size = output_path.stat().st_size if output_path.exists() else 0
    if current_size != offset:
        raise InvalidRequestError(
            "CSV 文件在 PREPARED 追加期间发生冲突修改",
            details={
                "local_path": str(output_path),
                "expected_size": offset,
                "actual_size": current_size,
            },
        )
    with output_path.open("ab") as csv_file:
        csv_file.write(payload)
        csv_file.flush()
        os.fsync(csv_file.fileno())
    journal.mark_committed(record)
    return resolved_fieldnames, resolved_write_header, False


def _render_csv_append_bytes(
    *,
    fieldnames: list[str],
    row: dict[str, str],
    write_header: bool,
) -> bytes:
    """把待追加的 CSV header 和 row 渲染为完整字节。"""

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    if write_header:
        writer.writeheader()
    writer.writerow({field_name: row.get(field_name, "") for field_name in fieldnames})
    return buffer.getvalue().encode("utf-8")


def _journal_payload_matches(
    output_path: Path,
    record: dict[str, object],
) -> bool:
    """判断 journal 描述的字节是否已经落到目标 offset。"""

    if not output_path.is_file():
        return False
    offset = _require_non_negative_int(record.get("offset"), field_name="offset")
    length = _require_non_negative_int(
        record.get("payload_length"),
        field_name="payload_length",
    )
    expected_digest = record.get("payload_sha256")
    if not isinstance(expected_digest, str):
        raise InvalidRequestError("CSV 追加 journal 缺少 payload_sha256")
    if output_path.stat().st_size < offset + length:
        return False
    with output_path.open("rb") as csv_file:
        csv_file.seek(offset)
        existing = csv_file.read(length)
    return sha256_bytes(existing) == expected_digest


def _require_non_negative_int(value: object, *, field_name: str) -> int:
    """读取 journal 中的非负整数字段。"""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequestError(f"CSV 追加 journal 的 {field_name} 无效")
    return value


def _resolve_fieldnames(
    *,
    output_path: Path,
    row: dict[str, str],
    field_order: tuple[str, ...] | None,
) -> tuple[list[str], bool]:
    """解析当前 CSV 应使用的表头。"""

    if field_order is not None:
        fieldnames = list(field_order)
        extra_keys = sorted(key for key in row if key not in fieldnames)
        if extra_keys:
            raise InvalidRequestError(
                "csv-append-local 当前行包含未声明在 field_order 中的字段",
                details={"extra_keys": extra_keys},
            )
        return fieldnames, not output_path.exists()
    if not output_path.exists():
        return sorted(row.keys()), True
    with output_path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.reader(csv_file)
        try:
            header_row = next(reader)
        except StopIteration:
            return sorted(row.keys()), True
    fieldnames = [field_name.strip() for field_name in header_row if field_name.strip()]
    extra_keys = sorted(key for key in row if key not in fieldnames)
    if extra_keys:
        raise InvalidRequestError(
            "csv-append-local 当前行字段与已有 CSV 表头不一致",
            details={"extra_keys": extra_keys, "fieldnames": fieldnames},
        )
    return fieldnames, False


def _read_field_order(request: WorkflowNodeExecutionRequest) -> tuple[str, ...] | None:
    """读取可选字段顺序。"""

    field_order = get_optional_str_tuple_parameter(request, "field_order")
    if field_order is None:
        return None
    return tuple(field_name.strip() for field_name in field_order)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.output.csv-append-local",
        display_name="Append CSV",
        category="core.io.file",
        description="把 result-record、alarm-record 或 value 追加到 ObjectStore 或 runtime 主机 CSV。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="result-record.v1",
                required=False,
            ),
            NodePortDefinition(
                name="alarm",
                display_name="Alarm",
                payload_type_id="alarm-record.v1",
                required=False,
            ),
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="save_location",
                display_name="保存位置",
                payload_type_id="value.v1",
                required=False,
            ),
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
                "save_location": {"type": "string", "title": "保存位置"},
                "field_order": {
                    "type": "array",
                    "title": "字段顺序",
                    "items": {"type": "string"},
                },
            },
        },
        capability_tags=("io.output", "inspection.result.persist", "csv.append"),
    ),
    handler=_csv_append_local_handler,
)
