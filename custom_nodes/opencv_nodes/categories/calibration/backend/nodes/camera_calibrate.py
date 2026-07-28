"""Camera Calibrate 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.runtime_support import load_image_matrix_from_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    read_bool,
    read_float,
    read_int,
    read_points,
    require_value_input,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads import (
    require_image_refs_payload,
)

NODE_TYPE_ID = "custom.opencv.camera-calibrate"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """从多张棋盘格图片估计针孔相机内参与畸变系数。"""

    cv2_module, np_module = require_opencv_imports()
    columns = read_int(
        request.parameters.get("columns"), field_name="columns", default=9, minimum=2
    )
    rows = read_int(
        request.parameters.get("rows"), field_name="rows", default=6, minimum=2
    )
    square_size = read_float(
        request.parameters.get("square_size"),
        field_name="square_size",
        default=1.0,
        minimum=1e-9,
    )
    min_views = read_int(
        request.parameters.get("min_views"),
        field_name="min_views",
        default=3,
        minimum=1,
    )
    use_sb = read_bool(
        request.parameters.get("use_sb"), field_name="use_sb", default=True
    )
    fix_aspect_ratio = read_bool(
        request.parameters.get("fix_aspect_ratio"),
        field_name="fix_aspect_ratio",
        default=False,
    )
    object_template = np_module.zeros((columns * rows, 3), dtype=np_module.float32)
    object_template[:, :2] = (
        np_module.mgrid[0:columns, 0:rows].T.reshape(-1, 2) * square_size
    )
    object_points: list[object] = []
    image_points: list[object] = []
    accepted_indices: list[int] = []
    rejected_indices: list[int] = []
    image_size: tuple[int, int] | None = None
    pattern_kind = "chessboard"
    pattern_size: list[int] | None = [columns, rows]
    pattern_spacing = square_size
    input_kind = "images"
    if request.input_values.get("observations") is not None:
        input_kind = "observations"
        observations_value = require_value_input(request, input_name="observations")
        raw_observations = (
            observations_value.get("items")
            if isinstance(observations_value, dict)
            else observations_value
        )
        if not isinstance(raw_observations, list):
            raise InvalidRequestError(
                "observations.value 必须是观测对象数组或包含 items 数组"
            )
        for index, raw_observation in enumerate(raw_observations, start=1):
            if not isinstance(raw_observation, dict):
                raise InvalidRequestError("observations 中的每个观测都必须是对象")
            current_size = _read_image_size(
                raw_observation.get("image_size"), index=index
            )
            image_size = _merge_image_size(
                image_size,
                current_size,
                index=index,
                node_name="camera-calibrate",
            )
            raw_object_points = read_points(
                raw_observation.get("object_points"),
                field_name="observation.object_points",
                minimum_count=4,
                dimensions=3,
            )
            raw_image_points = read_points(
                raw_observation.get("image_points"),
                field_name="observation.image_points",
                minimum_count=4,
            )
            if len(raw_object_points) != len(raw_image_points):
                raise InvalidRequestError(
                    "观测中的 object_points 与 image_points 数量必须一致"
                )
            object_points.append(
                np_module.asarray(raw_object_points, dtype=np_module.float32)
            )
            image_points.append(
                np_module.asarray(raw_image_points, dtype=np_module.float32).reshape(
                    -1, 1, 2
                )
            )
            accepted_indices.append(index)
            if index == 1:
                pattern_kind = str(raw_observation.get("pattern_kind") or "custom")
                raw_pattern_size = raw_observation.get("pattern_size")
                pattern_size = (
                    [int(value) for value in raw_pattern_size]
                    if isinstance(raw_pattern_size, list) and len(raw_pattern_size) == 2
                    else None
                )
                raw_spacing = raw_observation.get(
                    "square_size",
                    raw_observation.get("spacing"),
                )
                if (
                    isinstance(raw_spacing, (int, float))
                    and not isinstance(raw_spacing, bool)
                    and float(raw_spacing) > 0.0
                ):
                    pattern_spacing = float(raw_spacing)
    else:
        images_payload = require_image_refs_payload(request.input_values.get("images"))
        for index, image_payload in enumerate(images_payload["items"], start=1):
            _, image = load_image_matrix_from_payload(
                request,
                image_payload=image_payload,
                cv2_module=cv2_module,
                np_module=np_module,
                imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
            )
            current_size = (int(image.shape[1]), int(image.shape[0]))
            image_size = _merge_image_size(
                image_size,
                current_size,
                index=index,
                node_name="camera-calibrate",
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
            "有效标定视图数量不足",
            details={"accepted_count": len(object_points), "min_views": min_views},
        )
    camera_matrix = np_module.eye(3, dtype=np_module.float64)
    flags = 0
    if fix_aspect_ratio:
        flags |= cv2_module.CALIB_FIX_ASPECT_RATIO
    rms, camera_matrix, distortion, rotation_vectors, translation_vectors = (
        cv2_module.calibrateCamera(
            object_points,
            image_points,
            image_size,
            camera_matrix,
            None,
            flags=flags,
        )
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
        error = cv2_module.norm(image_item, projected, cv2_module.NORM_L2) / len(
            projected
        )
        per_view_errors.append(float(error))
    return {
        "calibration": build_value_payload(
            {
                "model": "pinhole",
                "pattern_kind": pattern_kind,
                "pattern_size": pattern_size,
                "square_size": pattern_spacing,
                "pattern_spacing": pattern_spacing,
                "image_size": list(image_size),
                "camera_matrix": camera_matrix.astype(float).tolist(),
                "distortion_coefficients": distortion.reshape(-1)
                .astype(float)
                .tolist(),
                "rms_reprojection_error": float(rms),
                "per_view_errors": per_view_errors,
                "rotation_vectors": [
                    value.reshape(-1).astype(float).tolist()
                    for value in rotation_vectors
                ],
                "translation_vectors": [
                    value.reshape(-1).astype(float).tolist()
                    for value in translation_vectors
                ],
                "accepted_indices": accepted_indices,
                "rejected_indices": rejected_indices,
                "view_count": len(accepted_indices),
                "use_sb": use_sb,
                "fix_aspect_ratio": fix_aspect_ratio,
                "input_kind": input_kind,
            }
        )
    }


def _read_image_size(raw_value: object, *, index: int) -> tuple[int, int]:
    """读取观测中的图片宽高。"""

    if (
        not isinstance(raw_value, list)
        or len(raw_value) != 2
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in raw_value
        )
    ):
        raise InvalidRequestError(
            "每个标定观测都必须提供正整数 image_size=[width, height]",
            details={"index": index},
        )
    return int(raw_value[0]), int(raw_value[1])


def _merge_image_size(
    current: tuple[int, int] | None,
    incoming: tuple[int, int],
    *,
    index: int,
    node_name: str,
) -> tuple[int, int]:
    """合并并校验多视图图片尺寸。"""

    if current is None:
        return incoming
    if current != incoming:
        raise InvalidRequestError(
            f"{node_name} 的所有视图尺寸必须一致",
            details={
                "expected": list(current),
                "actual": list(incoming),
                "index": index,
            },
        )
    return current


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
