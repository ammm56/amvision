"""按允许区域及显式搜索余量提取二值观察区域。"""

import math
import cv2
import numpy as np
from backend.nodes.core_nodes.support.roi import require_roi_list_payload
from backend.service.application.errors import InvalidRequestError
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import read_int
from .inspection_items import (
    binary_matrix,
    output_mask,
    mask_list,
    check_cancelled,
    validate_source,
)

NODE_TYPE_ID = "custom.opencv.roi-mask-extract"


def handle_node(request):
    """输入已二值化图，输出观察前景和允许域；不执行缺陷判定。"""
    image = binary_matrix(request, request.input_values.get("mask"))
    rois = require_roi_list_payload(request.input_values.get("rois"))["items"]
    if not 1 <= len(rois) <= 1024 or len({r["roi_id"] for r in rois}) != len(rois):
        raise InvalidRequestError("ROI 必须包含 1–1024 个唯一标识")
    margin = read_int(
        request.parameters.get("search_margin_pixels"),
        field_name="search_margin_pixels",
        default=0,
        minimum=0,
        maximum=128,
    )
    space = request.parameters.get("coordinate_space", "input-image")
    if not isinstance(space, str) or not space.strip():
        raise InvalidRequestError("必须明确声明共同坐标系名称")
    h, w = image.shape
    masks, allowed_masks = [], []
    for roi in rois:
        check_cancelled(request)
        if roi["roi_kind"] not in {"bbox", "polygon"}:
            raise InvalidRequestError("ROI Mask Extract 仅支持矩形和多边形")
        box = np.asarray(roi["bbox_xyxy"], dtype=float)
        points = np.asarray(roi["polygon_xy"], dtype=float)
        if (
            not np.isfinite(box).all()
            or not np.isfinite(points).all()
            or np.any(points < box[:2])
            or np.any(points > box[2:])
        ):
            raise InvalidRequestError("ROI 几何无效")
        x1, y1 = [math.floor(v) - margin for v in box[:2]]
        x2, y2 = [math.ceil(v) + margin for v in box[2:]]
        if not 0 <= x1 < x2 <= w or not 0 <= y1 < y2 <= h:
            raise InvalidRequestError("ROI 及搜索余量必须完整位于图像内")
        allowed = np.zeros((y2 - y1, x2 - x1), np.uint8)
        cv2.fillPoly(allowed, [np.rint(points - [x1, y1]).astype(np.int32)], 255)
        domain = (
            cv2.dilate(
                allowed,
                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * margin + 1,) * 2),
            )
            if margin
            else allowed
        )
        source = {
            k: roi[k] for k in ("roi_id", "roi_kind", "bbox_xyxy", "polygon_xy", "area")
        }
        source.update(
            coordinate_space=space,
            image_size=[w, h],
            observation_bbox_xyxy=[x1, y1, x2, y2],
            search_margin_pixels=margin,
        )
        validate_source(source, roi["roi_id"])
        if not np.any(allowed):
            raise InvalidRequestError("允许区域栅格化后为空")
        masks.append(
            output_mask(request, cv2.bitwise_and(image[y1:y2, x1:x2], domain), source)
        )
        allowed_masks.append(output_mask(request, allowed, source))
    return {"masks": mask_list(masks), "allowed_masks": mask_list(allowed_masks)}
