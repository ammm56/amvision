"""通用裁剪图读码：保留失败项及来源，位置只回映射至直接父图。"""

from dataclasses import replace

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.execution_control import (
    build_node_execution_control,
)
from custom_nodes.barcode_nodes.categories.compose.backend.nodes.qr_crop_decode_remap import (
    _remap_barcode_item,
)
from custom_nodes.barcode_nodes.shared.backend.runtime.decode import decode_barcodes
from custom_nodes.barcode_nodes.shared.backend.runtime.imports import (
    require_barcode_runtime_imports,
)

NODE_TYPE_ID = "custom.barcode.crop-decode"


def handle_node(request):
    """顺序解码 Crop Export 的裁剪图；不重试、不过滤失败项、不依赖位置配对。"""
    control = build_node_execution_control(request)
    control.raise_if_cancelled_or_expired()
    decode_scale = request.parameters.get("decode_scale", 1)
    if type(decode_scale) is not int or not 1 <= decode_scale <= 4:
        raise InvalidRequestError("decode_scale 必须是 1–4 的整数")
    crops = request.input_values.get("crops")
    if not isinstance(crops, dict) or not isinstance(crops.get("items"), list):
        raise InvalidRequestError("Crop Decode 需要 image-refs.v1 裁剪图列表")
    if len(crops["items"]) > 1024:
        raise InvalidRequestError("Crop Decode 一次最多处理 1024 张裁剪图")
    source = require_image_payload(crops.get("source_image"))
    formats = {
        "all-readable": ("AllReadable", "All Readable"),
        "data-matrix": ("DataMatrix", "Data Matrix"),
        "qr-code": ("QRCode", "QR Code"),
    }
    selected = request.parameters.get("format", "all-readable")
    if selected not in formats:
        raise InvalidRequestError("Crop Decode 条码格式不支持")
    member, label = formats[selected]
    _, _, zxing = require_barcode_runtime_imports()
    rows, decoded, identifiers = [], [], set()
    for crop in crops["items"]:
        control.raise_if_cancelled_or_expired()
        image = require_image_payload(crop)
        bbox, index = crop.get("bbox_xyxy"), crop.get("crop_index")
        if not isinstance(index, int) or isinstance(index, bool) or index < 1:
            raise InvalidRequestError("Crop Decode 要求裁剪图携带正整数 crop_index")
        item_id = crop.get("roi_id") or crop.get("region_id") or f"crop-{index}"
        if (
            not isinstance(item_id, str)
            or not item_id.strip()
            or item_id in identifiers
        ):
            raise InvalidRequestError("Crop Decode 的裁剪标识缺失或重复")
        identifiers.add(item_id)
        if (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or any(type(v) is not int for v in bbox)
        ):
            raise InvalidRequestError("Crop Decode 要求整数 bbox_xyxy")
        x1, y1, x2, y2 = bbox
        if not (
            0 <= x1 < x2 <= source["width"] and 0 <= y1 < y2 <= source["height"]
        ) or (x2 - x1, y2 - y1) != (image["width"], image["height"]):
            raise InvalidRequestError(
                "Crop Decode 裁剪坐标与父图或裁剪尺寸不一致；缩放图不能按平移回映射"
            )
        result = decode_barcodes(
            replace(request, input_values={"image": image}),
            barcode_format=getattr(zxing.BarcodeFormat, member),
            requested_format=label,
            decode_scale=decode_scale,
        )
        mapped = []
        for item in result["items"]:
            mapped_item = _remap_barcode_item(
                item=item,
                output_index=len(decoded) + 1,
                crop_index=index,
                crop_bbox=bbox,
            )
            mapped_item["extra"]["item_id"] = item_id
            mapped.append(mapped_item)
            decoded.append(mapped_item)
        valid = [i for i in mapped if i.get("valid")]
        state = (
            "decoded"
            if len(valid) == 1
            else ("ambiguous" if len(valid) > 1 else "unreadable")
        )
        rows.append(
            {
                "item_id": item_id,
                "source": {"bbox_xyxy": bbox, "crop_index": index},
                "result": {"state": state, "valid_count": len(valid), "items": mapped},
            }
        )
    results = {
        "requested_format": label,
        "source_image": source,
        "count": len(decoded),
        "matched_formats": list(dict.fromkeys(i["format"] for i in decoded)),
        "items": decoded,
    }
    summary = {
        "format_id": "amvision.barcode-crops.v1",
        "count": len(rows),
        "state": "no_candidates"
        if not rows
        else (
            "decoded"
            if all(i["result"]["state"] == "decoded" for i in rows)
            else "incomplete"
        ),
        "coordinate_space": "parent-image-pixels",
        "decode_scale": decode_scale,
        "items": rows,
    }
    return {"results": results, "summary": build_value_payload(summary)}
