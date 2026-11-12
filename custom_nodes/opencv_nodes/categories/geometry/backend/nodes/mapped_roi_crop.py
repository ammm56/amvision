"""按显式参考变换从原图直接裁剪校正 ROI，不生成整幅高分辨率校正图。"""

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, ValidationError
from typing import Annotated, Literal

from backend.nodes.core_nodes.support.logic import (
    build_value_payload,
    require_value_payload,
)
from backend.nodes.image_identity import build_image_identity
from backend.nodes.core_nodes.support.roi import iter_roi_payloads, require_roi_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.execution_control import (
    build_node_execution_control,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import (
    load_image_matrix,
    build_output_image_matrix_payload,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.transforms import (
    require_planar_transform_payload,
)

NODE_TYPE_ID = "custom.opencv.mapped-roi-crop"


class Settings(BaseModel):
    """ROI 使用参考原图坐标，coordinate_scale 明确声明定位图到原图的等比倍率。"""

    model_config = ConfigDict(extra="forbid")
    coordinate_scale: Annotated[FiniteFloat, Field(gt=0, le=64)] = 1
    roi_coordinate_scale: Annotated[FiniteFloat, Field(gt=0, le=64)] = 1
    interpolation: Literal["nearest", "linear", "cubic"] = "linear"
    maximum_total_pixels: Annotated[int, Field(ge=1, le=100_000_000)] = 25_000_000


class Region(BaseModel):
    """明确命名的参考矩形；原像素裁剪，不隐式缩放输出尺寸。"""

    model_config = ConfigDict(extra="forbid")
    roi_id: Annotated[str, Field(min_length=1, max_length=128)]
    bbox_xyxy: tuple[int, int, int, int]


def lift_transform(matrix, scale):
    """遵循 resize 像素中心规则，把定位图变换提升到原图坐标。"""
    resize = np.array(
        [[scale, 0, (scale - 1) / 2], [0, scale, (scale - 1) / 2], [0, 0, 1.0]]
    )
    return resize @ np.asarray(matrix, np.float64) @ np.linalg.inv(resize)


def crop_geometry(region, matrix, image_width, image_height):
    """返回裁剪到原图矩阵及原图四角，越界拒绝而不是补色后继续检测。"""
    x1, y1, x2, y2 = region.bbox_xyxy
    width, height = x2 - x1, y2 - y1
    if x1 < 0 or y1 < 0 or width <= 0 or height <= 0:
        raise ValueError("参考 ROI 必须是非负坐标的有效矩形")
    offset = np.array([[1, 0, x1], [0, 1, y1], [0, 0, 1.0]])
    source_from_crop = matrix @ offset
    corners = np.array(
        [[0, 0, 1], [width - 1, 0, 1], [width - 1, height - 1, 1], [0, height - 1, 1.0]]
    )
    projected = corners @ source_from_crop.T
    if np.any(abs(projected[:, 2]) < 1e-10) or not (
        np.all(projected[:, 2] > 0) or np.all(projected[:, 2] < 0)
    ):
        raise ValueError("ROI 跨越无效投影区域")
    polygon = projected[:, :2] / projected[:, 2, None]
    if (
        not np.isfinite(polygon).all()
        or polygon.min() < -1e-7
        or polygon[:, 0].max() > image_width - 1 + 1e-7
        or polygon[:, 1].max() > image_height - 1 + 1e-7
    ):
        raise ValueError("映射后的 ROI 超出原图，不能完整裁剪")
    return source_from_crop, polygon, (width, height)


def handle_node(request):
    """批量局部反向采样，输出显式坐标链、槽位标识和跳过记录。"""
    control = build_node_execution_control(request)
    control.raise_if_cancelled_or_expired()
    transform = require_planar_transform_payload(request.input_values.get("transform"))
    if (
        transform["source_coordinate_space"] != "template-image-pixels"
        or transform["target_coordinate_space"] != "source-image-pixels"
    ):
        raise InvalidRequestError("Mapped ROI Crop 要求参考图到当前图的变换")
    try:
        settings = Settings.model_validate(request.parameters)
        raw_roi = request.input_values.get("roi")
        raw_rois = request.input_values.get("rois")
        raw_items = request.input_values.get("roi_items")
        if sum(v is not None for v in (raw_roi, raw_rois, raw_items)) != 1:
            raise ValueError("roi、rois 与 roi_items 必须连接且仅连接一个")
        if raw_rois is not None:
            raw_roi = raw_rois
        if raw_roi is not None:
            raw = [
                {"roi_id": item["roi_id"], "bbox_xyxy": item["bbox_xyxy"]}
                for item in iter_roi_payloads(
                    raw_roi, node_id=request.node_id, field_name="roi"
                )
            ]
        else:
            raw = require_value_payload(raw_items, field_name="roi_items")["value"]
        if not isinstance(raw, list) or len(raw) > 1024:
            raise ValueError("roi_items 必须是不超过 1024 个矩形的数组")
        regions = []
        for item in raw:
            # ROI 坐标采用像素边界；先显式换算，再向外取整以保留完整工件。
            region = dict(item)
            if not isinstance(region.get("bbox_xyxy"), (list, tuple)) or any(
                isinstance(v, bool) or not isinstance(v, (int, float))
                for v in region["bbox_xyxy"]
            ):
                raise ValueError("ROI 坐标必须是数值数组")
            box = np.asarray(region["bbox_xyxy"], dtype=np.float64)
            if box.shape != (4,) or not np.isfinite(box).all():
                raise ValueError("ROI 坐标无效")
            box *= settings.roi_coordinate_scale
            region["bbox_xyxy"] = [int(np.floor(v)) for v in box[:2]] + [
                int(np.ceil(v)) for v in box[2:]
            ]
            regions.append(Region.model_validate(region))
    except (ValidationError, ValueError, TypeError, KeyError) as exc:
        raise InvalidRequestError("Mapped ROI Crop 参数或 ROI 列表无效") from exc
    ids = {region.roi_id for region in regions}
    if len(ids) != len(regions):
        raise InvalidRequestError("roi_id 不能重复")
    # 可选局部窗口直接合成到父区域，避免先生成整件图再二次裁剪。
    # window_roi 使用父裁图原像素坐标，不乘 roi_coordinate_scale。
    parent_regions = {region.roi_id: region for region in regions}
    window = request.input_values.get("window_roi")
    if window is not None:
        window = require_roi_payload(window)
        if window["roi_kind"] != "bbox":
            raise InvalidRequestError("局部窗口仅支持矩形 ROI")
        box = np.asarray(window["bbox_xyxy"], dtype=np.float64)
        if not np.isfinite(box).all():
            raise InvalidRequestError("局部窗口坐标必须是有限数值")
        wx1, wy1 = [int(np.floor(v)) for v in box[:2]]
        wx2, wy2 = [int(np.ceil(v)) for v in box[2:]]
        cropped_regions = []
        for parent in regions:
            px1, py1, px2, py2 = parent.bbox_xyxy
            if not (0 <= wx1 < wx2 <= px2 - px1 and 0 <= wy1 < wy2 <= py2 - py1):
                raise InvalidRequestError(
                    "局部窗口超出父 ROI，不能静默裁剪",
                    details={"roi_id": parent.roi_id},
                )
            cropped_regions.append(
                Region(
                    roi_id=parent.roi_id,
                    bbox_xyxy=(px1 + wx1, py1 + wy1, px1 + wx2, py1 + wy2),
                )
            )
        regions = cropped_regions
    selected = ids
    if request.input_values.get("selected_ids") is not None:
        value = require_value_payload(
            request.input_values["selected_ids"], field_name="selected_ids"
        )["value"]
        if (
            not isinstance(value, list)
            or any(not isinstance(v, str) for v in value)
            or len(set(value)) != len(value)
            or not set(value).issubset(ids)
        ):
            raise InvalidRequestError("selected_ids 必须是无重复的已定义 ROI 名称数组")
        selected = set(value)
    try:
        matrix = lift_transform(transform["matrix_3x3"], settings.coordinate_scale)
        if not np.isfinite(matrix).all() or abs(np.linalg.det(matrix)) <= 1e-12:
            raise ValueError("变换矩阵不可逆")
        for region in regions:
            x1, y1, x2, y2 = region.bbox_xyxy
            if min(x1, y1) < 0 or x2 <= x1 or y2 <= y1:
                raise ValueError("参考 ROI 矩形无效")
        pixels = sum(
            (r.bbox_xyxy[2] - r.bbox_xyxy[0]) * (r.bbox_xyxy[3] - r.bbox_xyxy[1])
            for r in regions
            if r.roi_id in selected
        )
        if pixels > settings.maximum_total_pixels:
            raise ValueError("裁剪输出像素总数超过显式上限")
    except ValueError as exc:
        raise InvalidRequestError(str(exc)) from exc
    crops, records = [], []
    if selected:
        payload, _, image = load_image_matrix(
            request, imdecode_flags=cv2.IMREAD_UNCHANGED
        )
        if image.dtype != np.uint8:
            raise InvalidRequestError(
                "Mapped ROI Crop 仅支持 uint8 图像；高位深图像须先显式转换"
            )
        height, width = image.shape[:2]
        source = transform.get("source_b_image", {})
        if (
            not source.get("width")
            or not source.get("height")
            or abs(source["width"] * settings.coordinate_scale - width) > 1e-6
            or abs(source["height"] * settings.coordinate_scale - height) > 1e-6
        ):
            raise InvalidRequestError("coordinate_scale 与定位图/原图尺寸不一致")
        identity = build_image_identity(payload, width=width, height=height)
        geometry = {}
        try:
            for region in regions:
                if region.roi_id in selected:
                    geometry[region.roi_id] = crop_geometry(
                        region, matrix, width, height
                    )
        except ValueError as exc:
            raise InvalidRequestError(str(exc)) from exc
    for region in regions:
        control.raise_if_cancelled_or_expired()
        record = {
            "item_id": region.roi_id,
            "reference_bbox_xyxy": list(region.bbox_xyxy),
            "state": "cropped" if region.roi_id in selected else "skipped",
            "reason": None if region.roi_id in selected else "not_selected",
        }
        if window is not None:
            record["parent_reference_bbox_xyxy"] = list(
                parent_regions[region.roi_id].bbox_xyxy
            )
            record["window_bbox_xyxy"] = [wx1, wy1, wx2, wy2]
        if region.roi_id in selected:
            source_from_crop, polygon, size = geometry[region.roi_id]
            interpolation = {
                "nearest": cv2.INTER_NEAREST,
                "linear": cv2.INTER_LINEAR,
                "cubic": cv2.INTER_CUBIC,
            }[settings.interpolation]
            output = cv2.warpPerspective(
                image,
                source_from_crop,
                size,
                flags=interpolation | cv2.WARP_INVERSE_MAP,
            )
            crop = build_output_image_matrix_payload(
                request,
                source_payload=payload,
                image_matrix=output,
                save_location=None,
                variant_name=f"mapped-crop-{len(crops) + 1}",
            )
            source_info = {
                "coordinate_space": "source-image-pixels",
                "image": identity,
                "polygon_xy": polygon.tolist(),
                "source_from_crop": source_from_crop.tolist(),
                "crop_from_source": np.linalg.inv(source_from_crop).tolist(),
            }
            crop.update(
                roi_id=region.roi_id,
                crop_index=len(crops) + 1,
                crop_source="mapped-roi",
                reference_bbox_xyxy=list(region.bbox_xyxy),
                mapped_source=source_info,
            )
            record["source"] = source_info
            crops.append(crop)
        records.append(record)
    return {
        "crops": {"items": crops, "count": len(crops)},
        "summary": build_value_payload(
            {
                "count": len(records),
                "cropped_count": len(crops),
                "skipped_count": len(records) - len(crops),
                "items": records,
            }
        ),
    }
