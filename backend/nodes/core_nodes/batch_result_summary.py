"""批次结果摘要节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._batch_result_summary_node_support import (
    build_batch_result_summary,
    clone_inline_json_value,
    read_result_item_list_from_multi_payload,
    read_result_item_list_from_raw_value,
    read_result_item_list_from_value_payload,
)
from backend.nodes.core_nodes._logic_node_support import (
    build_value_payload,
    require_value_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


NODE_NAME = "batch-result-summary"


def _batch_result_summary_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """把一批 result-record 收成批次摘要。"""

    record_value = _read_optional_record_value(request.input_values.get("record"))
    record_result_items = _read_record_result_items(record_value)
    direct_result_items = read_result_item_list_from_value_payload(
        request.input_values.get("inspection_results"),
        node_name=NODE_NAME,
        field_name="inspection_results",
    ) + read_result_item_list_from_multi_payload(
        request.input_values.get("inspection_result"),
        node_name=NODE_NAME,
        field_name="inspection_result",
    )
    all_result_items = [*record_result_items, *direct_result_items]

    used_precomputed_summary = False
    summary_source = "computed"
    if all_result_items:
        summary_value = build_batch_result_summary(all_result_items)
    else:
        precomputed_summary = _read_optional_precomputed_summary(record_value)
        if precomputed_summary is not None:
            summary_value = precomputed_summary
            used_precomputed_summary = True
            summary_source = "record.inspection_result_summary"
        else:
            summary_value = build_batch_result_summary(())
            summary_source = "empty"

    summary_value = dict(summary_value)
    summary_value["summary_source"] = summary_source
    summary_value["source_record"] = record_value is not None
    summary_value["record_result_count"] = len(record_result_items)
    summary_value["direct_result_count"] = len(direct_result_items)
    summary_value["used_precomputed_summary"] = used_precomputed_summary

    return {"summary": build_value_payload(summary_value)}


def _read_optional_record_value(
    input_payload: object,
) -> dict[str, object] | None:
    """读取可选批次记录对象。"""

    if input_payload is None:
        return None
    raw_value = require_value_payload(input_payload, field_name="record")["value"]
    if not isinstance(raw_value, dict):
        raise InvalidRequestError(f"{NODE_NAME} 的 record.value 必须是对象")
    return clone_inline_json_value(raw_value)


def _read_record_result_items(
    record_value: dict[str, object] | None,
) -> list[dict[str, object]]:
    """从批次记录对象中读取 inspection_results。"""

    if record_value is None:
        return []
    raw_value = record_value.get("inspection_results")
    if raw_value is None:
        return []
    return read_result_item_list_from_raw_value(
        raw_value,
        node_name=NODE_NAME,
        field_name="record.inspection_results",
    )


def _read_optional_precomputed_summary(
    record_value: dict[str, object] | None,
) -> dict[str, object] | None:
    """读取 batch-record 中已有的预计算摘要。"""

    if record_value is None:
        return None
    raw_value = record_value.get("inspection_result_summary")
    if raw_value is None:
        return None
    if not isinstance(raw_value, dict):
        raise InvalidRequestError(
            f"{NODE_NAME} 的 record.inspection_result_summary 必须是对象"
        )
    return clone_inline_json_value(raw_value)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.output.batch-result-summary",
        display_name="Batch Result Summary",
        category="inspection.output",
        description="把一批 result-record.v1 收成 ok/ng/alarm/pass-ratio 等批次摘要，适合目录批处理归档和结果回传。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="record",
                display_name="Record",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="inspection_results",
                display_name="Inspection Results",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="inspection_result",
                display_name="Inspection Result",
                payload_type_id="result-record.v1",
                required=False,
                multiple=True,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
        capability_tags=("inspection.output", "inspection.batch-summary", "integration.output"),
    ),
    handler=_batch_result_summary_handler,
)
