"""Classification Items To Regions 节点测试。"""

from __future__ import annotations

import pytest

from backend.nodes.core_catalog import get_core_workflow_node_definitions
from backend.nodes.core_nodes.vision.regions.classification_items_to_regions import (
    CORE_NODE_SPEC,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def test_catalog_contains_classification_items_to_regions() -> None:
    """节点应进入公开 Core catalog。"""

    node_ids = {
        definition.node_type_id for definition in get_core_workflow_node_definitions()
    }
    assert "core.vision.classification-items-to-regions" in node_ids


def test_classification_items_to_regions_joins_by_roi_id_and_uses_roi_order() -> None:
    """并行分支顺序和局部 item_index 不得改变最终 ROI 对应关系。"""

    output = _invoke(
        items=[
            _classification_item("roi-c", item_index=0, class_id=3),
            _classification_item("roi-a", item_index=0, class_id=1),
            _classification_item("roi-b", item_index=1, class_id=2),
        ],
        roi_ids=["roi-a", "roi-b", "roi-c"],
    )

    regions = output["regions"]
    assert [item["region_id"] for item in regions["items"]] == [
        "roi-a",
        "roi-b",
        "roi-c",
    ]
    assert [item["class_id"] for item in regions["items"]] == [1, 2, 3]
    assert [item["source_item_index"] for item in regions["items"]] == [0, 1, 0]
    assert regions["source_image"]["content_sha256"] == "parent-sha"
    assert output["summary"]["value"]["identity_match_modes"] == {
        "content-sha256": 3
    }


@pytest.mark.parametrize(
    ("case_name", "message"),
    (
        ("item-id-mismatch", "item_id 与 source.roi_id 一致"),
        ("unknown-roi", "未知 source.roi_id"),
        ("duplicate-roi", "source.roi_id 不能重复"),
        ("missing-roi", "完整一一对应"),
    ),
)
def test_classification_items_to_regions_rejects_ambiguous_associations(
    case_name: str,
    message: str,
) -> None:
    """缺失、未知、重复或交叉 ID 都必须确定性失败。"""

    cases = {
        "item-id-mismatch": (
            [_classification_item("roi-a", item_id="wrong")],
            ["roi-a"],
        ),
        "unknown-roi": ([_classification_item("roi-unknown")], ["roi-a"]),
        "duplicate-roi": (
            [_classification_item("roi-a"), _classification_item("roi-a")],
            ["roi-a"],
        ),
        "missing-roi": ([_classification_item("roi-a")], ["roi-a", "roi-b"]),
    }
    items, roi_ids = cases[case_name]
    with pytest.raises(InvalidRequestError, match=message):
        _invoke(items=items, roi_ids=roi_ids)


def test_classification_items_to_regions_rejects_parent_image_mismatch() -> None:
    """Batch source 父图身份与绘制图片不一致时不得继续。"""

    item = _classification_item("roi-a")
    item["source"]["source_image_identity"]["content_sha256"] = "other-sha"
    with pytest.raises(InvalidRequestError, match="content_sha256 不一致"):
        _invoke(items=[item], roi_ids=["roi-a"])


def test_classification_items_to_regions_rejects_dimension_only_identity() -> None:
    """同尺寸图片不能在缺少 content_sha256 时被推断为同一父图。"""

    item = _classification_item("roi-a")
    item["source"]["source_image_identity"].pop("content_sha256")
    with pytest.raises(InvalidRequestError, match="必须提供.*content_sha256"):
        _invoke(items=[item], roi_ids=["roi-a"])


def _invoke(
    *,
    items: list[dict[str, object]],
    roi_ids: list[str],
) -> dict[str, object]:
    """执行节点。"""

    image = _source_image()
    return CORE_NODE_SPEC.handler(
        WorkflowNodeExecutionRequest(
            node_id="classification-items-to-regions",
            node_definition=CORE_NODE_SPEC.node_definition,
            parameters={},
            input_values={
                "items": {"value": items},
                "rois": {
                    "format_id": "amvision.roi-list.v1",
                    "count": len(roi_ids),
                    "items": [
                        {
                            "roi_id": roi_id,
                            "roi_kind": "bbox",
                            "bbox_xyxy": [index * 10, 0, index * 10 + 8, 8],
                            "polygon_xy": [
                                [index * 10, 0],
                                [index * 10 + 8, 0],
                                [index * 10 + 8, 8],
                                [index * 10, 8],
                            ],
                            "area": 64,
                            "source_image": image,
                        }
                        for index, roi_id in enumerate(roi_ids)
                    ],
                },
                "image": image,
            },
            execution_metadata={},
        )
    )


def _classification_item(
    roi_id: str,
    *,
    item_id: str | None = None,
    item_index: int = 0,
    class_id: int = 1,
) -> dict[str, object]:
    """构造完整 Batch 关联项。"""

    category = {
        "class_id": class_id,
        "class_name": f"class-{class_id}",
        "probability": 0.9,
    }
    return {
        "item_index": item_index,
        "item_id": item_id or roi_id,
        "source": {
            "roi_id": roi_id,
            "crop_index": item_index + 1,
            "bbox_xyxy": [0, 0, 8, 8],
            "source_image_identity": {
                "format_id": "amvision.image-identity.v1",
                "content_sha256": "parent-sha",
                "width": 100,
                "height": 80,
            },
        },
        "result": {
            "count": 1,
            "items": [category],
            "top_item": category,
        },
    }


def _source_image() -> dict[str, object]:
    """构造带内容身份的源图引用。"""

    return {
        "transport_kind": "memory",
        "image_handle": "source-image",
        "media_type": "image/raw",
        "content_sha256": "parent-sha",
        "width": 100,
        "height": 80,
    }
