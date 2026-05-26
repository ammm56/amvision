"""QR crop decode + remap 节点实现。"""

from __future__ import annotations

from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.barcode_protocol_nodes.backend.support import (
    decode_barcodes,
    require_barcode_position_payload,
    require_image_refs_payload,
    require_barcode_runtime_imports,
)
from custom_nodes.barcode_protocol_nodes.specs import QR_CROP_DECODE_REMAP_NODE_TYPE_ID


NODE_TYPE_ID = QR_CROP_DECODE_REMAP_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """逐个解码 crop 图片中的 QR Code，并回映射到 source_image 坐标系。

    参数：
    - request：当前 workflow 节点执行请求；要求输入端提供 crop-export 产出的 crops payload。

    返回：
    - dict[str, object]：统一 barcode-results.v1 结果，position 已平移到原图坐标系。
    """

    _, _, zxing_module = require_barcode_runtime_imports()
    crops_payload = require_image_refs_payload(request.input_values.get("crops"))
    source_image_payload = _require_source_image_payload(crops_payload)
    source_object_key = crops_payload.get("source_object_key")

    remapped_items: list[dict[str, object]] = []
    for crop_list_index, crop_payload in enumerate(crops_payload["items"], start=1):
        crop_bbox = _require_crop_bbox(crop_payload, crop_list_index=crop_list_index)
        crop_request = WorkflowNodeExecutionRequest(
            node_id=f"{request.node_id}.crop-{crop_list_index}",
            node_definition=request.node_definition,
            parameters=dict(request.parameters),
            input_values={"image": crop_payload},
            execution_metadata=request.execution_metadata,
            runtime_context=request.runtime_context,
        )
        crop_results = decode_barcodes(
            crop_request,
            barcode_format=zxing_module.BarcodeFormat.QRCode,
            requested_format="QR Code",
        )
        crop_index = int(crop_payload.get("crop_index", crop_list_index))
        for item in crop_results.get("items", []):
            if not isinstance(item, dict):
                continue
            remapped_items.append(
                _remap_barcode_item(
                    item=item,
                    output_index=len(remapped_items) + 1,
                    crop_index=crop_index,
                    crop_bbox=crop_bbox,
                )
            )

    results_payload: dict[str, object] = {
        "requested_format": "QR Code",
        "source_image": dict(source_image_payload),
        "count": len(remapped_items),
        "matched_formats": list(
            dict.fromkeys(
                item["format"] for item in remapped_items if isinstance(item.get("format"), str)
            )
        ),
        "items": remapped_items,
    }
    if isinstance(source_object_key, str) and source_object_key:
        results_payload["source_object_key"] = source_object_key
    return {"results": results_payload}


def _require_source_image_payload(crops_payload: dict[str, object]) -> dict[str, object]:
    """读取并校验 crops.source_image。"""

    source_image_payload = crops_payload.get("source_image")
    if not isinstance(source_image_payload, dict):
        raise InvalidRequestError(
            "qr-crop-decode-remap 节点要求 crops.source_image 必须是 image-ref 对象"
        )
    return require_image_payload(source_image_payload)


def _require_crop_bbox(crop_payload: dict[str, object], *, crop_list_index: int) -> list[int]:
    """读取单个 crop 的原图 bbox。"""

    crop_bbox = crop_payload.get("bbox_xyxy")
    if (
        not isinstance(crop_bbox, list)
        or len(crop_bbox) != 4
        or not all(isinstance(value, int) for value in crop_bbox)
    ):
        raise InvalidRequestError(
            "qr-crop-decode-remap 节点要求每个 crop 都带 bbox_xyxy",
            details={"crop_list_index": crop_list_index},
        )
    return list(crop_bbox)


def _remap_barcode_item(
    *,
    item: dict[str, object],
    output_index: int,
    crop_index: int,
    crop_bbox: list[int],
) -> dict[str, object]:
    """把单个 crop 内的 barcode item 平移回原图坐标系。"""

    offset_x = int(crop_bbox[0])
    offset_y = int(crop_bbox[1])
    position_payload = require_barcode_position_payload(item.get("position"))
    remapped_item = dict(item)
    remapped_item["index"] = output_index
    remapped_item["position"] = _shift_position_payload(
        position_payload,
        offset_x=offset_x,
        offset_y=offset_y,
    )
    extra_payload = dict(item.get("extra")) if isinstance(item.get("extra"), dict) else {}
    extra_payload["crop_index"] = crop_index
    extra_payload["crop_bbox_xyxy"] = list(crop_bbox)
    remapped_item["extra"] = extra_payload
    return remapped_item


def _shift_position_payload(
    position_payload: dict[str, object],
    *,
    offset_x: int,
    offset_y: int,
) -> dict[str, object]:
    """把 barcode position 中的所有点位平移到原图坐标系。"""

    remapped_position = dict(position_payload)
    remapped_position["top_left_xy"] = _shift_point(position_payload["top_left_xy"], offset_x=offset_x, offset_y=offset_y)
    remapped_position["top_right_xy"] = _shift_point(position_payload["top_right_xy"], offset_x=offset_x, offset_y=offset_y)
    remapped_position["bottom_right_xy"] = _shift_point(
        position_payload["bottom_right_xy"],
        offset_x=offset_x,
        offset_y=offset_y,
    )
    remapped_position["bottom_left_xy"] = _shift_point(
        position_payload["bottom_left_xy"],
        offset_x=offset_x,
        offset_y=offset_y,
    )
    remapped_position["polygon_xy"] = [
        _shift_point(point, offset_x=offset_x, offset_y=offset_y)
        for point in position_payload["polygon_xy"]
    ]
    bounds_xyxy = position_payload.get("bounds_xyxy")
    if isinstance(bounds_xyxy, list) and len(bounds_xyxy) == 4:
        remapped_position["bounds_xyxy"] = [
            int(bounds_xyxy[0]) + offset_x,
            int(bounds_xyxy[1]) + offset_y,
            int(bounds_xyxy[2]) + offset_x,
            int(bounds_xyxy[3]) + offset_y,
        ]
    center_xy = position_payload.get("center_xy")
    if isinstance(center_xy, list) and len(center_xy) == 2:
        remapped_position["center_xy"] = [
            float(center_xy[0]) + offset_x,
            float(center_xy[1]) + offset_y,
        ]
    return remapped_position


def _shift_point(point: list[int], *, offset_x: int, offset_y: int) -> list[int]:
    """把单个二维点按指定偏移量平移。"""

    return [int(point[0]) + offset_x, int(point[1]) + offset_y]