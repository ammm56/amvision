"""分类 Batch 完整关联项与 ROI 的确定性合并节点。"""

from __future__ import annotations

from collections import Counter

from backend.contracts.workflows.workflow_graph import (
    NODE_CONCURRENCY_THREAD_SAFE,
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
from backend.nodes.core_nodes.support.region import build_regions_payload
from backend.nodes.core_nodes.support.roi import require_roi_list_payload
from backend.nodes.core_nodes.support.typed_payload_bridges import (
    require_categories_payload,
)
from backend.nodes.image_identity import (
    build_image_identity,
    require_image_identity,
    require_matching_image_identity,
)
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


NODE_TYPE_ID = "core.vision.classification-items-to-regions"


def _classification_items_to_regions_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """按 source.roi_id 连接分类项与 ROI，并按 ROI 顺序输出 regions.v1。"""

    source_image = require_image_payload(request.input_values.get("image"))
    target_image_identity = build_image_identity(source_image)
    roi_list = require_roi_list_payload(
        request.input_values.get("rois"),
        node_id=request.node_id,
        field_name="rois",
    )
    roi_items = roi_list["items"]
    roi_by_id = _build_unique_roi_index(
        roi_items,
        target_image_identity=target_image_identity,
        node_id=request.node_id,
    )
    raw_items = require_value_payload(
        request.input_values.get("items"),
        field_name="items",
    )["value"]
    if not isinstance(raw_items, list):
        raise InvalidRequestError(
            "Classification Items To Regions 要求 items.value 必须是数组",
            details={"node_id": request.node_id},
        )

    classification_by_roi_id: dict[str, dict[str, object]] = {}
    identity_match_modes: Counter[str] = Counter()
    for list_index, raw_item in enumerate(raw_items):
        normalized_item, match_mode = _normalize_classification_item(
            raw_item,
            list_index=list_index,
            target_image_identity=target_image_identity,
            node_id=request.node_id,
        )
        roi_id = str(normalized_item["roi_id"])
        if roi_id not in roi_by_id:
            raise InvalidRequestError(
                "Classification Items To Regions 收到未知 source.roi_id",
                details={
                    "node_id": request.node_id,
                    "list_index": list_index,
                    "roi_id": roi_id,
                },
            )
        if roi_id in classification_by_roi_id:
            raise InvalidRequestError(
                "Classification Items To Regions 的 source.roi_id 不能重复",
                details={"node_id": request.node_id, "roi_id": roi_id},
            )
        classification_by_roi_id[roi_id] = normalized_item
        identity_match_modes[match_mode] += 1

    missing_roi_ids = [
        str(roi["roi_id"])
        for roi in roi_items
        if str(roi["roi_id"]) not in classification_by_roi_id
    ]
    if missing_roi_ids:
        raise InvalidRequestError(
            "Classification Items To Regions 要求分类项与 ROI 完整一一对应",
            details={
                "node_id": request.node_id,
                "missing_roi_ids": missing_roi_ids,
                "classification_count": len(classification_by_roi_id),
                "roi_count": len(roi_items),
            },
        )

    region_items = [
        _build_region_item(
            roi_item=roi_item,
            classification_item=classification_by_roi_id[str(roi_item["roi_id"])],
        )
        for roi_item in roi_items
    ]
    class_distribution = Counter(
        str(region_item["class_name"]) for region_item in region_items
    )
    return {
        "regions": build_regions_payload(
            source_image=source_image,
            selected_frame_index=None,
            items=region_items,
        ),
        "summary": build_value_payload(
            {
                "format_id": "amvision.classification-items-to-regions-summary.v1",
                "match_policy": "exact-roi-id",
                "output_order": "roi-list",
                "item_count": len(raw_items),
                "roi_count": len(roi_items),
                "region_count": len(region_items),
                "identity_match_modes": dict(sorted(identity_match_modes.items())),
                "class_distribution": dict(sorted(class_distribution.items())),
            }
        ),
    }


def _build_unique_roi_index(
    roi_items: list[dict[str, object]],
    *,
    target_image_identity: dict[str, object],
    node_id: str,
) -> dict[str, dict[str, object]]:
    """校验 ROI 唯一性及其来源图片，并构建 roi_id 索引。"""

    roi_by_id: dict[str, dict[str, object]] = {}
    for list_index, roi_item in enumerate(roi_items):
        roi_id = str(roi_item["roi_id"])
        if roi_id in roi_by_id:
            raise InvalidRequestError(
                "Classification Items To Regions 的 ROI ID 不能重复",
                details={"node_id": node_id, "roi_id": roi_id},
            )
        raw_source_image = roi_item.get("source_image")
        if not isinstance(raw_source_image, dict):
            raise InvalidRequestError(
                "Classification Items To Regions 要求每个 ROI 都带 source_image",
                details={
                    "node_id": node_id,
                    "list_index": list_index,
                    "roi_id": roi_id,
                },
            )
        roi_image_identity = build_image_identity(
            require_image_payload(raw_source_image)
        )
        match_mode = require_matching_image_identity(
            roi_image_identity,
            target_image_identity,
            field_name=f"rois[{list_index}].source_image",
            node_id=node_id,
        )
        _require_content_sha256_match(
            match_mode,
            field_name=f"rois[{list_index}].source_image",
            node_id=node_id,
        )
        roi_by_id[roi_id] = roi_item
    return roi_by_id


def _normalize_classification_item(
    raw_item: object,
    *,
    list_index: int,
    target_image_identity: dict[str, object],
    node_id: str,
) -> tuple[dict[str, object], str]:
    """校验单个完整 Batch item 并提取顶级分类。"""

    if not isinstance(raw_item, dict):
        raise InvalidRequestError(
            "Classification Items To Regions 要求每个 item 都是 object",
            details={"node_id": node_id, "list_index": list_index},
        )
    raw_item_index = raw_item.get("item_index")
    if (
        isinstance(raw_item_index, bool)
        or not isinstance(raw_item_index, int)
        or raw_item_index < 0
    ):
        raise InvalidRequestError(
            "Classification Items To Regions 要求 item_index 是非负整数",
            details={"node_id": node_id, "list_index": list_index},
        )
    item_id = raw_item.get("item_id")
    if not isinstance(item_id, str) or not item_id.strip():
        raise InvalidRequestError(
            "Classification Items To Regions 要求 item_id 不能为空",
            details={"node_id": node_id, "list_index": list_index},
        )
    source = raw_item.get("source")
    if not isinstance(source, dict):
        raise InvalidRequestError(
            "Classification Items To Regions 要求 source 必须是 object",
            details={"node_id": node_id, "list_index": list_index},
        )
    roi_id = source.get("roi_id")
    if not isinstance(roi_id, str) or not roi_id.strip():
        raise InvalidRequestError(
            "Classification Items To Regions 要求 source.roi_id 不能为空",
            details={"node_id": node_id, "list_index": list_index},
        )
    normalized_item_id = item_id.strip()
    normalized_roi_id = roi_id.strip()
    if normalized_item_id != normalized_roi_id:
        raise InvalidRequestError(
            "Classification Items To Regions 要求 item_id 与 source.roi_id 一致",
            details={
                "node_id": node_id,
                "list_index": list_index,
                "item_id": normalized_item_id,
                "roi_id": normalized_roi_id,
            },
        )
    source_image_identity = require_image_identity(
        source.get("source_image_identity"),
        field_name=f"items[{list_index}].source.source_image_identity",
        node_id=node_id,
    )
    match_mode = require_matching_image_identity(
        source_image_identity,
        target_image_identity,
        field_name=f"items[{list_index}].source.source_image_identity",
        node_id=node_id,
    )
    _require_content_sha256_match(
        match_mode,
        field_name=f"items[{list_index}].source.source_image_identity",
        node_id=node_id,
    )
    categories = require_categories_payload(raw_item.get("result"), node_id)
    top_item = categories.get("top_item")
    if not isinstance(top_item, dict):
        raise InvalidRequestError(
            "Classification Items To Regions 要求 result.top_item 存在",
            details={
                "node_id": node_id,
                "list_index": list_index,
                "item_id": normalized_item_id,
            },
        )
    class_id = int(top_item["class_id"])
    raw_class_name = top_item.get("class_name")
    class_name = (
        raw_class_name.strip()
        if isinstance(raw_class_name, str) and raw_class_name.strip()
        else f"class-{class_id}"
    )
    return (
        {
            "item_index": raw_item_index,
            "item_id": normalized_item_id,
            "roi_id": normalized_roi_id,
            "source": dict(source),
            "class_id": class_id,
            "class_name": class_name,
            "score": float(top_item["probability"]),
        },
        match_mode,
    )


def _require_content_sha256_match(
    match_mode: str,
    *,
    field_name: str,
    node_id: str,
) -> None:
    """禁止把同尺寸图片推断为同一父图。"""

    if match_mode != "content-sha256":
        raise InvalidRequestError(
            f"{field_name} 必须提供可与目标图片核对的 content_sha256",
            details={"node_id": node_id, "match_mode": match_mode},
        )


def _build_region_item(
    *,
    roi_item: dict[str, object],
    classification_item: dict[str, object],
) -> dict[str, object]:
    """使用权威 ROI 几何和对应分类结果构造 region。"""

    region_item: dict[str, object] = {
        "region_id": str(roi_item["roi_id"]),
        "score": float(classification_item["score"]),
        "class_id": int(classification_item["class_id"]),
        "class_name": str(classification_item["class_name"]),
        "bbox_xyxy": list(roi_item["bbox_xyxy"]),
        "polygon_xy": [list(point) for point in roi_item["polygon_xy"]],
        "area": int(roi_item["area"]),
        "source_item_id": str(classification_item["item_id"]),
        "source_item_index": classification_item.get("item_index"),
    }
    if isinstance(roi_item.get("display_name"), str):
        region_item["display_name"] = roi_item["display_name"]
    source = classification_item["source"]
    if isinstance(source, dict):
        if source.get("crop_index") is not None:
            region_item["source_crop_index"] = source["crop_index"]
        if isinstance(source.get("bbox_xyxy"), list):
            region_item["source_bbox_xyxy"] = list(source["bbox_xyxy"])
    return region_item


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id=NODE_TYPE_ID,
        display_name="Classification Items To Regions",
        category="core.vision.region",
        description=(
            "按 items[*].source.roi_id 将分类 Batch 完整关联项与 ROI 严格一一连接，"
            "并按 ROI 列表顺序输出可直接绘制的 regions.v1。"
        ),
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        concurrency_policy=NODE_CONCURRENCY_THREAD_SAFE,
        input_ports=(
            NodePortDefinition(
                name="items",
                display_name="Classification Items",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="rois",
                display_name="ROIs",
                payload_type_id="roi-list.v1",
            ),
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
            ),
            NodePortDefinition(
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
        capability_tags=(
            "vision.region",
            "vision.region.classification",
            "payload.batch.items",
        ),
    ),
    handler=_classification_items_to_regions_handler,
)
