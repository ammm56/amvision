"""Camera Calibrate 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.runtime_support import load_image_matrix_from_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    read_bool,
    read_float,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads import require_image_refs_payload

NODE_TYPE_ID = "custom.opencv.camera-calibrate"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """从多张棋盘格图片估计针孔相机内参与畸变系数。"""

    cv2_module, np_module = require_opencv_imports()
    images_payload = require_image_refs_payload(request.input_values.get("images"))
    columns = read_int(request.parameters.get("columns"), field_name="columns", default=9, minimum=2)
    rows = read_int(request.parameters.get("rows"), field_name="rows", default=6, minimum=2)
    square_size = read_float(request.parameters.get("square_size"), field_name="square_size", default=1.0, minimum=1e-9)
    min_views = read_int(request.parameters.get("min_views"), field_name="min_views", default=3, minimum=1)
    use_sb = read_bool(request.parameters.get("use_sb"), field_name="use_sb", default=True)
    fix_aspect_ratio = read_bool(
        request.parameters.get("fix_aspect_ratio"),
        field_name="fix_aspect_ratio",
        default=False,
    )
    object_template = np_module.zeros((columns * rows, 3), dtype=np_module.float32)
    object_template[:, :2] = np_module.mgrid[0:columns, 0:rows].T.reshape(-1, 2) * square_size
    object_points: list[object] = []
    image_points: list[object] = []
    accepted_indices: list[int] = []
    rejected_indices: list[int] = []
    image_size: tuple[int, int] | None = None
    for index, image_payload in enumerate(images_payload["items"], start=1):
        _, image = load_image_matrix_from_payload(
            request,
            image_payload=image_payload,
            cv2_module=cv2_module,
            np_module=np_module,
            imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
        )
        current_size = (int(image.shape[1]), int(image.shape[0]))
        if image_size is None:
            image_size = current_size
        elif image_size != current_size:
            raise InvalidRequestError(
                "camera-calibrate 的所有图片尺寸必须一致",
                details={"expected": list(image_size), "actual": list(current_size), "index": index},
            )
        found, corners = _find_corners(
            image,
            columns=columns,
            rows=rows,
            use_sb=use_sb,
            cv2_module=cv2_module,
        )
        if not found or corners is None:
            rejected_indices.append(index)
            continue
        object_points.append(object_template.copy())
        image_points.append(corners.astype(np_module.float32))
        accepted_indices.append(index)
    if image_size is None or len(object_points) < min_views:
        raise InvalidRequestError(
            "有效棋盘格视图数量不足",
            details={"accepted_count": len(object_points), "min_views": min_views},
        )
    camera_matrix = np_module.eye(3, dtype=np_module.float64)
    flags = 0
    if fix_aspect_ratio:
        flags |= cv2_module.CALIB_FIX_ASPECT_RATIO
    rms, camera_matrix, distortion, rotation_vectors, translation_vectors = cv2_module.calibrateCamera(
        object_points,
        image_points,
        image_size,
        camera_matrix,
        None,
        flags=flags,
    )
    per_view_errors = []
    for object_item, image_item, rotation, translation in zip(
        object_points,
        image_points,
        rotation_vectors,
        translation_vectors,
        strict=True,
    ):
        projected, _ = cv2_module.projectPoints(
            object_item,
            rotation,
            translation,
            camera_matrix,
            distortion,
        )
        error = cv2_module.norm(image_item, projected, cv2_module.NORM_L2) / len(projected)
        per_view_errors.append(float(error))
    return {
        "calibration": build_value_payload(
            {
                "model": "pinhole",
                "pattern_kind": "chessboard",
                "pattern_size": [columns, rows],
                "square_size": square_size,
                "image_size": list(image_size),
                "camera_matrix": camera_matrix.astype(float).tolist(),
                "distortion_coefficients": distortion.reshape(-1).astype(float).tolist(),
                "rms_reprojection_error": float(rms),
                "per_view_errors": per_view_errors,
                "rotation_vectors": [value.reshape(-1).astype(float).tolist() for value in rotation_vectors],
                "translation_vectors": [value.reshape(-1).astype(float).tolist() for value in translation_vectors],
                "accepted_indices": accepted_indices,
                "rejected_indices": rejected_indices,
                "view_count": len(accepted_indices),
                "use_sb": use_sb,
                "fix_aspect_ratio": fix_aspect_ratio,
            }
        )
    }


def _find_corners(
    gray: object,
    *,
    columns: int,
    rows: int,
    use_sb: bool,
    cv2_module: object,
) -> tuple[bool, object | None]:
    """检测并细化棋盘格内角点。"""

    if use_sb and hasattr(cv2_module, "findChessboardCornersSB"):
        return cv2_module.findChessboardCornersSB(
            gray,
            (columns, rows),
            flags=cv2_module.CALIB_CB_NORMALIZE_IMAGE | cv2_module.CALIB_CB_EXHAUSTIVE,
        )
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
    return bool(found), corners
