"""本地 CSV 结果追加节点。"""

from __future__ import annotations

import csv
from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._local_io_node_support import (
    build_local_file_summary,
    flatten_mapping_for_csv,
    resolve_local_output_file_path,
    resolve_value_or_result_input,
)
from backend.nodes.core_nodes._service_node_support import get_optional_str_tuple_parameter
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _csv_append_local_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把结果对象、报警对象或 value 追加到本地 CSV 文件。"""

    output_path = resolve_local_output_file_path(
        request,
        parameter_name="local_path",
        overwrite=True,
        description="本地 CSV 输出文件",
    )
    payload_value, record_kind = resolve_value_or_result_input(request)
    row = flatten_mapping_for_csv(payload_value)
    field_order = _read_field_order(request)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames, write_header = _resolve_fieldnames(
        output_path=output_path,
        row=row,
        field_order=field_order,
    )
    with output_path.open("a", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow({field_name: row.get(field_name, "") for field_name in fieldnames})
    return {
        "summary": build_local_file_summary(
            local_path=output_path,
            extra_fields={
                "record_kind": record_kind,
                "field_count": len(fieldnames),
                "fieldnames": list(fieldnames),
                "wrote_header": write_header,
            },
        )
    }


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
        display_name="Append Local CSV",
        category="io.output",
        description="把 result-record、alarm-record 或 value 内容扁平化后追加到本地 CSV 文件。",
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
                name="path",
                display_name="Path",
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
                "local_path": {"type": "string", "title": "本地 CSV 路径"},
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
