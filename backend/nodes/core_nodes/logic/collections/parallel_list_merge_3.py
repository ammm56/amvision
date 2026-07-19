"""通用三路并行列表有序合并节点。"""

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
    PARALLEL_LIST_MERGE_3_NODE_TYPE_ID,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _parallel_list_merge_3_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """严格按 part_1、part_2、part_3 顺序连接三个列表。"""

    merged_items: list[object] = []
    for partition_index in range(1, 4):
        merged_items.extend(
            require_list_value(
                request.input_values.get(f"part_{partition_index}"),
                field_name=f"part_{partition_index}",
                node_id=request.node_id,
            )
        )
    return {
        "items": build_value_payload(merged_items),
        "count": build_value_payload(len(merged_items)),
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
        node_type_id=PARALLEL_LIST_MERGE_3_NODE_TYPE_ID,
        display_name="Ordered List Merge 3",
        category="logic.parallel",
        description=(
            "严格按第一、第二、第三分区的顺序连接三个列表，并声明三条受控并行分支的结束边界。"
            "节点只处理通用列表，不依赖图片、ROI、模型或具体 Workflow App。"
        ),
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=tuple(
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
        output_ports=(
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
            NodePortDefinition(
                name="count",
                display_name="Count",
                payload_type_id="value.v1",
                metadata={
                    "localized_display_name": _localized_text(
                        "数量", "Count", "件数", "개수"
                    )
                },
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
        capability_tags=(
            "logic.collection",
            "logic.parallel",
            "parallel.boundary.end",
            "parallel.list.merge.3",
            "execution.pure",
        ),
        metadata={
            "localized_display_name": _localized_text(
                "三路并行列表有序合并",
                "Ordered List Merge 3",
                "3 分岐並列リスト順序結合",
                "3분기 병렬 목록 순서 병합",
            ),
            "localized_description": _localized_text(
                "等待三条显式并行分支完成，并严格按分区1、2、3的顺序连接结果。适用于任意 Workflow App 和任意列表数据。",
                "Wait for three explicit parallel branches and concatenate their results strictly in partition order 1, 2, 3. It works with any workflow data.",
                "3つの明示的な並列分岐を待ち、パート1、2、3の順序で結果を結合します。",
                "3개의 명시적 병렬 분기가 끝날 때까지 기다린 뒤 파트 1, 2, 3 순서로 결과를 병합합니다.",
            ),
        },
    ),
    handler=_parallel_list_merge_3_handler,
)
