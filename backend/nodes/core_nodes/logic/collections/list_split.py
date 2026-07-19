"""List 分区逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.collection import require_list_value
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


MAX_LIST_PARTITION_COUNT = 1024


def _list_split_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按原始顺序把 Items 平衡拆成指定数量的连续 partitions。"""

    items = require_list_value(
        request.input_values.get("items"),
        field_name="items",
        node_id=request.node_id,
    )
    partition_count = request.parameters.get("partition_count", 1)
    if isinstance(partition_count, bool) or not isinstance(partition_count, int):
        raise InvalidRequestError(
            "Split List 要求 partition_count 必须是整数",
            details={"node_id": request.node_id, "partition_count": partition_count},
        )
    if not 1 <= partition_count <= MAX_LIST_PARTITION_COUNT:
        raise InvalidRequestError(
            "Split List 的 partition_count 必须在 1 到 1024 之间",
            details={"node_id": request.node_id, "partition_count": partition_count},
        )

    quotient, remainder = divmod(len(items), partition_count)
    partitions: list[list[object]] = []
    start_index = 0
    for partition_index in range(partition_count):
        partition_size = quotient + (1 if partition_index < remainder else 0)
        end_index = start_index + partition_size
        partitions.append(items[start_index:end_index])
        start_index = end_index
    return {
        "partitions": build_value_payload(partitions),
        "count": build_value_payload(len(partitions)),
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.list-split",
        display_name="Split List",
        category="logic.collection",
        description=(
            "按原始顺序将 Items 平衡拆成 partition_count 个连续 partitions。"
            "输出可配合 Get List Item 和 Parallel Start 构造任意数量的显式分支。"
        ),
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="items",
                display_name="Items",
                payload_type_id="value.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="partitions",
                display_name="Partitions",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="count",
                display_name="Count",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "partition_count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_LIST_PARTITION_COUNT,
                    "default": 1,
                },
            },
        },
        capability_tags=("logic.collection", "list.split", "execution.pure"),
    ),
    handler=_list_split_handler,
)
