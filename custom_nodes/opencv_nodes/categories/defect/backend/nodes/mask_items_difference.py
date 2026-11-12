"""两组显式匹配掩膜的有向差集和面积测量。"""

import cv2
import numpy as np
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import read_int
from .inspection_items import (
    read_masks,
    pair_items,
    binary_matrix,
    output_mask,
    mask_list,
    records,
    check_cancelled,
)

NODE_TYPE_ID = "custom.opencv.mask-items-difference"


def handle_node(request):
    """计算 A 减 dilate(B)，明确输出两种分母的比例，不作 OK/NG 判定。"""
    a = read_masks(request.input_values.get("masks_a"))
    b = read_masks(request.input_values.get("masks_b"))
    radius = read_int(
        request.parameters.get("tolerance_pixels"),
        field_name="tolerance_pixels",
        default=0,
        minimum=0,
        maximum=64,
    )
    kernel = (
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1,) * 2)
        if radius
        else None
    )
    masks, items = [], []
    for key, left, right in pair_items(a, b, masks=True):
        check_cancelled(request)
        ma, mb = binary_matrix(request, left), binary_matrix(request, right)
        if ma.shape != mb.shape:
            from backend.service.application.errors import InvalidRequestError

            raise InvalidRequestError("配对掩膜尺寸不同")
        difference = cv2.bitwise_and(
            ma, cv2.bitwise_not(cv2.dilate(mb, kernel) if kernel is not None else mb)
        )
        aa, ab, ad = (int(np.count_nonzero(m)) for m in (ma, mb, difference))
        source = left["measurement_source"]
        masks.append(output_mask(request, difference, source))
        items.append(
            {
                "item_id": key,
                "source": source,
                "result": {
                    "area_a": aa,
                    "area_b": ab,
                    "difference_area": ad,
                    "ratio_to_a": ad / aa if aa else None,
                    "ratio_to_b": ad / ab if ab else None,
                    "tolerance_pixels": radius,
                },
            }
        )
    return {"masks": mask_list(masks), "metrics": records(items)}
