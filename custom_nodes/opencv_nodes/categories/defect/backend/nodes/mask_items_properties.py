"""二值前景的像素面积、质心与无向主轴测量。"""

import cv2
import numpy as np
from .inspection_items import read_masks, binary_matrix, records, check_cancelled
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import read_float

NODE_TYPE_ID = "custom.opencv.mask-items-properties"


def handle_node(request):
    """按像素二阶矩测量，孔洞保留；近圆前景不输出不稳定的角度。"""
    minimum = read_float(
        request.parameters.get("min_axis_anisotropy"),
        field_name="min_axis_anisotropy",
        default=0.1,
        minimum=0,
        maximum=1,
    )
    items = []
    for key, mask in read_masks(request.input_values.get("masks")).items():
        check_cancelled(request)
        matrix = binary_matrix(request, mask)
        m = cv2.moments(matrix, binaryImage=True)
        area = int(m["m00"])
        center, angle, anisotropy = None, None, None
        source = mask["measurement_source"]
        if area > 0:
            x, y = source["observation_bbox_xyxy"][:2]
            center = [x + m["m10"] / area, y + m["m01"] / area]
            values, vectors = np.linalg.eigh(
                np.array([[m["mu20"], m["mu11"]], [m["mu11"], m["mu02"]]]) / area
            )
            anisotropy = float((values[1] - values[0]) / max(values[1], 1e-12))
            if values[1] > 0 and anisotropy >= minimum:
                angle = float(np.degrees(np.arctan2(vectors[1, 1], vectors[0, 1])))
        items.append(
            {
                "item_id": key,
                "source": source,
                "result": {
                    "area": area,
                    "center_xy": center,
                    "axis_angle_degrees": angle,
                    "axis_anisotropy": anisotropy,
                    "min_axis_anisotropy": minimum,
                },
            }
        )
    return {"metrics": records(items)}
