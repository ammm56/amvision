"""用已生成的测量和判定绘图，不重新测量或改变 OK/NG。"""

import math
import cv2
import numpy as np
from backend.nodes.runtime_support import register_typed_image_matrix
from backend.service.application.errors import InvalidRequestError
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from .inspection_items import (
    read_records,
    read_masks,
    binary_matrix,
    same_source,
    mask_list,
    check_cancelled,
)

NODE_TYPE_ID = "custom.opencv.draw-inspection-items"


def handle_node(request):
    """输出逐区域原图、证据掩膜、质心/轴线及测量值，独立接 Gallery Preview。"""
    checks = read_records(
        request.input_values.get("checks"),
        expected_format="amvision.inspection-check-items.v1",
    )
    masks = (
        read_masks(request.input_values["masks"])
        if request.input_values.get("masks") is not None
        else None
    )
    if masks is not None and masks.keys() != checks.keys():
        raise InvalidRequestError("绘图掩膜与检查结果的标识集合不一致")
    _, _, image = load_image_matrix(request)
    images = []
    for key, item in checks.items():
        check_cancelled(request)
        source = item["source"]
        if source["image_size"] != [image.shape[1], image.shape[0]]:
            raise InvalidRequestError("绘制图像与测量坐标系尺寸不一致")
        x1, y1, x2, y2 = source["observation_bbox_xyxy"]
        if not 0 <= x1 < x2 <= image.shape[1] or not 0 <= y1 < y2 <= image.shape[0]:
            raise InvalidRequestError("绘制观察区域超出图片")
        canvas = image[y1:y2, x1:x2].copy()
        if masks is not None:
            same_source(source, masks[key]["measurement_source"])
            mask = binary_matrix(request, masks[key])
            if mask.shape != canvas.shape[:2]:
                raise InvalidRequestError("证据掩膜与观察区域尺寸不一致")
            selected = mask != 0
            canvas[selected] = (
                canvas[selected] * 0.35 + np.array([0, 100, 255]) * 0.65
            ).astype(np.uint8)
        result = item["result"]
        color = (86, 122, 8) if result.get("passed") is True else (50, 50, 220)
        points = np.rint(np.asarray(source["polygon_xy"]) - [x1, y1]).astype(np.int32)
        cv2.polylines(canvas, [points], True, color, 2)
        measurement = result.get("measurement", {})
        for pose_name, pose_color in (
            ("reference_pose", (0, 220, 220)),
            ("current_pose", (255, 150, 0)),
        ):
            pose = measurement.get(pose_name)
            if not isinstance(pose, dict) or pose.get("center_xy") is None:
                continue
            center = np.asarray(pose["center_xy"]) - [x1, y1]
            point = tuple(np.rint(center).astype(int))
            cv2.drawMarker(canvas, point, pose_color, cv2.MARKER_CROSS, 14, 2)
            angle = pose.get("axis_angle_degrees")
            if angle is not None:
                vector = (
                    np.array(
                        [math.cos(math.radians(angle)), math.sin(math.radians(angle))]
                    )
                    * min(canvas.shape[:2])
                    * 0.25
                )
                cv2.line(
                    canvas,
                    tuple(np.rint(center - vector).astype(int)),
                    tuple(np.rint(center + vector).astype(int)),
                    pose_color,
                    2,
                )
        value = result.get("value")
        value_text = (
            f"{value:.4g}" if isinstance(value, (float, int)) else "unavailable"
        )
        lines = [
            f"{key} | {result.get('check_id', 'check')} | {result.get('state', 'unknown')}",
            f"{result.get('metric', 'value')}={value_text} {result.get('unit', '')}",
            f"min={result.get('minimum')} max={result.get('maximum')}",
        ]
        width = max(
            canvas.shape[1],
            max(
                cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)[0][0]
                for line in lines
            )
            + 16,
        )
        rendered = np.full((canvas.shape[0] + 66, width, 3), 32, np.uint8)
        rendered[66:, : canvas.shape[1]] = canvas
        for i, line in enumerate(lines):
            cv2.putText(
                rendered,
                line,
                (8, 16 + i * 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (240, 240, 240),
                1,
                cv2.LINE_AA,
            )
        output = register_typed_image_matrix(request, image_matrix=rendered)
        # 可视图有标题边，不得冒充与原图同坐标的算法输入。
        output.update(
            roi_id=key,
            inspection_check_id=result.get("check_id"),
            visualization_only=True,
        )
        images.append(output)
    return {"images": mask_list(images)}
