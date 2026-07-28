"""Chessboard Corners 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    ensure_gray,
    read_bool,
    read_float,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports

NODE_TYPE_ID = "custom.opencv.chessboard-corners"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """检测棋盘格内角点并输出标定观测。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, _, image = load_image_matrix(request)
    gray = ensure_gray(image, cv2_module=cv2_module)
    columns = read_int(request.parameters.get("columns"), field_name="columns", default=9, minimum=2)
    rows = read_int(request.parameters.get("rows"), field_name="rows", default=6, minimum=2)
    square_size = read_float(request.parameters.get("square_size"), field_name="square_size", default=1.0, minimum=1e-9)
    use_sb = read_bool(request.parameters.get("use_sb"), field_name="use_sb", default=True)
    if use_sb and hasattr(cv2_module, "findChessboardCornersSB"):
        found, corners = cv2_module.findChessboardCornersSB(
            gray,
            (columns, rows),
            flags=cv2_module.CALIB_CB_NORMALIZE_IMAGE | cv2_module.CALIB_CB_EXHAUSTIVE,
        )
    else:
        found, corners = cv2_module.findChessboardCorners(
            gray,
            (columns, rows),
            flags=cv2_module.CALIB_CB_ADAPTIVE_THRESH | cv2_module.CALIB_CB_NORMALIZE_IMAGE,
        )
        if found:
            corners = cv2_module.cornerSubPix(
                gray,
                corners,
                (11, 11),
                (-1, -1),
                (cv2_module.TERM_CRITERIA_EPS | cv2_module.TERM_CRITERIA_COUNT, 30, 0.001),
            )
    if not found or corners is None:
        raise InvalidRequestError(
            "未检测到完整棋盘格",
            details={"columns": columns, "rows": rows},
        )
    object_points = np_module.zeros((columns * rows, 3), dtype=np_module.float32)
    object_points[:, :2] = np_module.mgrid[0:columns, 0:rows].T.reshape(-1, 2) * square_size
    return {
        "observation": build_value_payload(
            {
                "pattern_kind": "chessboard",
                "pattern_size": [columns, rows],
                "square_size": square_size,
                "image_size": [int(gray.shape[1]), int(gray.shape[0])],
                "image_points": corners.reshape(-1, 2).astype(float).tolist(),
                "object_points": object_points.astype(float).tolist(),
                "source_image": image_payload,
                "point_count": int(corners.shape[0]),
                "subpixel_refined": not use_sb,
            }
        )
    }
