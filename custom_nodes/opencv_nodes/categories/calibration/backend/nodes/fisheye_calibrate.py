"""从标定图片或观测对象估计 OpenCV fisheye 模型参数。"""

from __future__ import annotations

from typing import Any

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.runtime_support import load_image_matrix_from_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
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

NODE_TYPE_ID = "custom.opencv.fisheye-calibrate"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行 fisheye 相机标定并输出可直接用于矫正的参数。"""

    cv2, np = require_opencv_imports()
    columns = read_int(
        request.parameters.get("columns"),
        field_name="columns",
        default=9,
        minimum=2,
    )
    rows = read_int(
        request.parameters.get("rows"),
        field_name="rows",
        default=6,
        minimum=2,
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
    object_template = np.zeros((columns * rows, 1, 3), dtype=np.float64)
    object_template[:, 0, :2] = (
        np.mgrid[0:columns, 0:rows].T.reshape(-1, 2) * square_size
    )
    object_points: list[Any] = []
    image_points: list[Any] = []
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
        for index, observation in enumerate(raw_observations, start=1):
            if not isinstance(observation, dict):
                raise InvalidRequestError("observations 中的每个观测都必须是对象")
            raw_size = observation.get("image_size")
            if (
                not isinstance(raw_size, list)
                or len(raw_size) != 2
                or any(
                    isinstance(value, bool) or not isinstance(value, int) or value <= 0
                    for value in raw_size
                )
            ):
                raise InvalidRequestError("每个 fisheye 标定观测都必须提供 image_size")
            size = (int(raw_size[0]), int(raw_size[1]))
            if image_size is None:
                image_size = size
            elif image_size != size:
                raise InvalidRequestError("fisheye-calibrate 的所有观测尺寸必须一致")

            raw_object_points = read_points(
                observation.get("object_points"),
                field_name="observation.object_points",
                minimum_count=4,
                dimensions=3,
            )
            raw_image_points = read_points(
                observation.get("image_points"),
                field_name="observation.image_points",
                minimum_count=4,
            )
            if len(raw_object_points) != len(raw_image_points):
                raise InvalidRequestError(
                    "观测中的 object_points 与 image_points 数量必须一致"
                )
            object_points.append(
                np.asarray(raw_object_points, dtype=np.float64).reshape(-1, 1, 3)
            )
            image_points.append(
                np.asarray(raw_image_points, dtype=np.float64).reshape(-1, 1, 2)
            )
            accepted_indices.append(index)
            if index == 1:
                pattern_kind = str(observation.get("pattern_kind") or "custom")
                raw_pattern_size = observation.get("pattern_size")
                pattern_size = (
                    [int(value) for value in raw_pattern_size]
                    if isinstance(raw_pattern_size, list) and len(raw_pattern_size) == 2
                    else None
                )
                raw_spacing = observation.get(
                    "square_size",
                    observation.get("spacing"),
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
            _, gray = load_image_matrix_from_payload(
                request,
                image_payload=image_payload,
                cv2_module=cv2,
                np_module=np,
                imdecode_flags=cv2.IMREAD_GRAYSCALE,
            )
            size = (int(gray.shape[1]), int(gray.shape[0]))
            if image_size is None:
                image_size = size
            elif image_size != size:
                raise InvalidRequestError("fisheye-calibrate 的所有图片尺寸必须一致")
            found, corners = cv2.findChessboardCorners(
                gray,
                (columns, rows),
                flags=cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE,
            )
            if not found or corners is None:
                rejected_indices.append(index)
                continue
            refined = cv2.cornerSubPix(
                gray,
                corners,
                (11, 11),
                (-1, -1),
                (
                    cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
                    30,
                    0.001,
                ),
            )
            object_points.append(object_template.copy())
            image_points.append(refined.astype(np.float64).reshape(-1, 1, 2))
            accepted_indices.append(index)

    if image_size is None or len(object_points) < min_views:
        raise InvalidRequestError(
            "有效 fisheye 标定视图数量不足",
            details={"accepted_count": len(object_points), "min_views": min_views},
        )
    pinhole_object_points = [
        item.reshape(-1, 3).astype(np.float32) for item in object_points
    ]
    pinhole_image_points = [
        item.reshape(-1, 1, 2).astype(np.float32) for item in image_points
    ]
    _, camera_matrix, _, _, _ = cv2.calibrateCamera(
        pinhole_object_points,
        pinhole_image_points,
        image_size,
        None,
        None,
    )
    camera_matrix = camera_matrix.astype(np.float64)
    distortion = np.zeros((4, 1), dtype=np.float64)
    flags = cv2.fisheye.CALIB_FIX_SKEW | cv2.fisheye.CALIB_USE_INTRINSIC_GUESS
    rms, camera_matrix, distortion, rotations, translations = cv2.fisheye.calibrate(
        object_points,
        image_points,
        image_size,
        camera_matrix,
        distortion,
        None,
        None,
        flags=flags,
        criteria=(
            cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
            100,
            1e-7,
        ),
    )
    return {
        "calibration": build_value_payload(
            {
                "model": "fisheye",
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
                "rotation_vectors": [
                    item.reshape(-1).astype(float).tolist() for item in rotations
                ],
                "translation_vectors": [
                    item.reshape(-1).astype(float).tolist() for item in translations
                ],
                "accepted_indices": accepted_indices,
                "rejected_indices": rejected_indices,
                "view_count": len(accepted_indices),
                "input_kind": input_kind,
            }
        )
    }


__all__ = ["NODE_TYPE_ID", "handle_node"]
