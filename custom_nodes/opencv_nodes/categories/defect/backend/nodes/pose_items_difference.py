"""已测量质心与无向主轴之间的差值，不重新进行图像分割。"""

import math
from .inspection_items import (
    read_records,
    pair_items,
    records,
    finite_number,
    check_cancelled,
)
from backend.service.application.errors import InvalidRequestError

NODE_TYPE_ID = "custom.opencv.pose-items-difference"


def handle_node(request):
    """按 item_id 配对；输出公共图像坐标中的有向偏移及 0–90° 无向轴差。"""
    current = read_records(request.input_values.get("current"))
    reference = read_records(request.input_values.get("reference"))
    items = []
    for key, a, b in pair_items(current, reference):
        check_cancelled(request)
        ca, cb = a["result"].get("center_xy"), b["result"].get("center_xy")
        for pose in (a["result"], b["result"]):
            if "center_xy" not in pose or "axis_angle_degrees" not in pose:
                raise InvalidRequestError("位姿记录缺少质心或主轴字段")
            center, axis = pose["center_xy"], pose["axis_angle_degrees"]
            if center is not None and not (
                isinstance(center, list)
                and len(center) == 2
                and all(finite_number(v) for v in center)
            ):
                raise InvalidRequestError("质心必须为有限二维坐标或 null")
            if axis is not None and not finite_number(axis):
                raise InvalidRequestError("主轴必须为有限角度或 null")
        dx, dy, distance = None, None, None
        if ca is not None and cb is not None:
            if not all(
                isinstance(c, list) and len(c) == 2 and all(finite_number(v) for v in c)
                for c in (ca, cb)
            ):
                raise InvalidRequestError("质心必须为有限二维坐标或 null")
            dx, dy = ca[0] - cb[0], ca[1] - cb[1]
            distance = math.hypot(dx, dy)
        aa, ab = (
            a["result"].get("axis_angle_degrees"),
            b["result"].get("axis_angle_degrees"),
        )
        angle = (
            abs((aa - ab + 90) % 180 - 90)
            if finite_number(aa) and finite_number(ab)
            else None
        )
        items.append(
            {
                "item_id": key,
                "source": a["source"],
                "result": {
                    "dx": dx,
                    "dy": dy,
                    "centroid_shift_pixels": distance,
                    "axis_angle_difference_degrees": angle,
                    "current_pose": a["result"],
                    "reference_pose": b["result"],
                },
            }
        )
    return {"metrics": records(items)}
