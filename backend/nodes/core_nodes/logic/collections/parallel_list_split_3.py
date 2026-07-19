"""通用三路并行列表拆分节点。"""

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
from backend.service.application.workflows.execution.parallel_list import (
    PARALLEL_LIST_SPLIT_3_NODE_TYPE_ID,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _parallel_list_split_3_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """把列表按原始顺序平衡拆成三个连续分区。"""

    items = require_list_value(
        request.input_values.get("items"),
        field_name="items",
        node_id=request.node_id,
    )
    quotient, remainder = divmod(len(items), 3)
    partitions: list[list[object]] = []
    start_index = 0
    for partition_index in range(3):
        partition_size = quotient + (1 if partition_index < remainder else 0)
        end_index = start_index + partition_size
        partitions.append(items[start_index:end_index])
        start_index = end_index
    return {
        "part_1": build_value_payload(partitions[0]),
        "part_2": build_value_payload(partitions[1]),
        "part_3": build_value_payload(partitions[2]),
    }


def _localized_text(zh_cn: str, en_us: str, ja_jp: str, ko_kr: str) -> dict[str, str]:
    """构造前端可直接读取的四语言文本。"""

    return {
        "zh-CN": zh_cn,
        "en-US": en_us,
        "ja-JP": ja_jp,
        "ko-KR": ko_kr,
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id=PARALLEL_LIST_SPLIT_3_NODE_TYPE_ID,
        display_name="Parallel List Split 3",
        category="logic.parallel",
        description=(
            "把一个列表按原始顺序平衡拆成三个连续分区，并声明三条受控并行分支的开始边界。"
            "节点只处理通用列表，不依赖图片、ROI、模型或具体 Workflow App。"
        ),
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="items",
                display_name="Items",
                payload_type_id="value.v1",
                metadata={
                    "localized_display_name": _localized_text(
                        "列表", "Items", "リスト", "목록"
                    )
                },
            ),
        ),
        output_ports=tuple(
            NodePortDefinition(
                name=f"part_{index}",
                display_name=f"Part {index}",
                payload_type_id="value.v1",
                metadata={
                    "localized_display_name": _localized_text(
                        f"分区 {index}",
                        f"Part {index}",
                        f"パート {index}",
                        f"파트 {index}",
                    )
                },
            )
            for index in range(1, 4)
        ),
        parameter_schema={"type": "object", "properties": {}},
        capability_tags=(
            "logic.collection",
            "logic.parallel",
            "parallel.boundary.start",
            "parallel.list.split.3",
            "execution.pure",
        ),
        metadata={
            "localized_display_name": _localized_text(
                "三路并行列表拆分",
                "Parallel List Split 3",
                "3 分岐並列リスト分割",
                "3분기 병렬 목록 분할",
            ),
            "localized_description": _localized_text(
                "按原始顺序把列表平衡拆成三个连续分区，作为三条显式并行分支的开始边界。适用于任意 Workflow App 和任意列表数据。",
                "Split a list into three balanced contiguous partitions while preserving order. This is the explicit start boundary for three parallel branches and works with any workflow data.",
                "順序を維持したままリストを3つの連続パートに均等分割し、明示的な並列分岐の開始境界にします。",
                "순서를 유지한 채 목록을 3개의 연속 파트로 균등 분할하고 명시적 병렬 분기의 시작 경계로 사용합니다.",
            ),
        },
    ),
    handler=_parallel_list_split_3_handler,
)
