"""工业二维视觉标定观察、诊断、双目标定和校正 map 节点。"""

from __future__ import annotations

from io import BytesIO
import hashlib
import json
import math
from typing import Any

from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.nodes.runtime_support import require_dataset_storage
from backend.nodes.save_locations import (
    SAVE_LOCATION_OBJECT_STORE,
    resolve_required_save_location_from_request,
    save_bytes,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.execution_control import (
    build_node_execution_control,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    read_float,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import (
    build_typed_output_image_matrix_payload,
    load_image_matrix,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads import (
    require_camera_calibration_payload,
    require_stereo_calibration_payload,
)

OBSERVATION_FILTER_NODE_TYPE_ID = "custom.opencv.calibration-observation-filter"
CALIBRATION_DIAGNOSE_NODE_TYPE_ID = "custom.opencv.calibration-diagnose"
STEREO_CALIBRATE_NODE_TYPE_ID = "custom.opencv.stereo-calibrate"
STEREO_RECTIFY_NODE_TYPE_ID = "custom.opencv.stereo-rectify"
RECTIFICATION_MAP_NODE_TYPE_ID = "custom.opencv.rectification-map"
IMAGE_RECTIFY_STEREO_NODE_TYPE_ID = "custom.opencv.image-rectify-stereo"


def handle_observation_filter(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """按点数、覆盖率、中心分布和可选重投影误差筛选标定观察。"""

    execution_control = build_node_execution_control(request)
    execution_control.raise_if_cancelled_or_expired()
    observations = _require_observations(request, input_name="observations")
    minimum_points = read_int(
        request.parameters.get("minimum_points"),
        field_name="minimum_points",
        default=12,
        minimum=4,
        maximum=100000,
    )
    minimum_coverage = read_float(
        request.parameters.get("minimum_coverage_ratio"),
        field_name="minimum_coverage_ratio",
        default=0.02,
        minimum=0.0,
        maximum=1.0,
    )
    maximum_error = read_float(
        request.parameters.get("maximum_reprojection_error"),
        field_name="maximum_reprojection_error",
        default=5.0,
        minimum=0.0,
    )
    minimum_center_distance = read_float(
        request.parameters.get("minimum_center_distance_ratio"),
        field_name="minimum_center_distance_ratio",
        default=0.02,
        minimum=0.0,
        maximum=1.0,
    )
    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    accepted_centers: list[tuple[float, float]] = []
    for observation_index, observation in enumerate(observations, start=1):
        execution_control.raise_if_cancelled_or_expired()
        image_points = _require_image_points(observation)
        image_size = _require_image_size(observation)
        point_array = _as_float_points(image_points)
        width, height = image_size
        bbox_width = max(item[0] for item in point_array) - min(item[0] for item in point_array)
        bbox_height = max(item[1] for item in point_array) - min(item[1] for item in point_array)
        coverage = max(0.0, bbox_width * bbox_height / (width * height))
        center = (
            sum(item[0] for item in point_array) / len(point_array) / width,
            sum(item[1] for item in point_array) / len(point_array) / height,
        )
        reasons: list[str] = []
        if len(point_array) < minimum_points:
            reasons.append("insufficient-point-count")
        if coverage < minimum_coverage:
            reasons.append("insufficient-image-coverage")
        raw_error = observation.get("reprojection_error")
        if isinstance(raw_error, int | float) and not isinstance(raw_error, bool):
            if float(raw_error) > maximum_error:
                reasons.append("reprojection-error-exceeded")
        if accepted_centers and min(
            math.hypot(center[0] - item[0], center[1] - item[1])
            for item in accepted_centers
        ) < minimum_center_distance:
            reasons.append("duplicate-image-position")
        diagnostics = {
            "index": observation_index,
            "point_count": len(point_array),
            "coverage_ratio": coverage,
            "normalized_center_xy": list(center),
            "reasons": reasons,
        }
        if reasons:
            rejected.append(diagnostics)
        else:
            normalized = dict(observation)
            normalized["filter_diagnostics"] = diagnostics
            accepted.append(normalized)
            accepted_centers.append(center)
    payload = {
        "format_id": "amvision.calibration-observations.v1",
        "count": len(accepted),
        "items": accepted,
    }
    diagnostics = {
        "format_id": "amvision.calibration-observation-filter.v1",
        "input_count": len(observations),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "rejected": rejected,
    }
    return {
        "observations": build_value_payload(payload),
        "diagnostics": build_value_payload(diagnostics),
    }


def handle_calibration_diagnose(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """重新计算逐观察重投影误差、覆盖率和异常观察。"""

    execution_control = build_node_execution_control(request)
    execution_control.raise_if_cancelled_or_expired()
    cv2_module, np_module = require_opencv_imports()
    calibration = require_camera_calibration_payload(
        request.input_values.get("camera_calibration")
    )
    observations = _require_observations(request, input_name="observations")
    camera_matrix = np_module.asarray(calibration["camera_matrix"], dtype=np_module.float64)
    distortion = np_module.asarray(
        calibration["distortion_coefficients"],
        dtype=np_module.float64,
    )
    maximum_error = read_float(
        request.parameters.get("maximum_reprojection_error"),
        field_name="maximum_reprojection_error",
        default=2.0,
        minimum=0.0,
    )
    items = []
    squared_errors: list[float] = []
    for index, observation in enumerate(observations, start=1):
        execution_control.raise_if_cancelled_or_expired()
        object_points = np_module.asarray(
            _require_object_points(observation),
            dtype=np_module.float32,
        )
        image_points = np_module.asarray(
            _require_image_points(observation),
            dtype=np_module.float32,
        ).reshape(-1, 1, 2)
        success, rotation, translation = cv2_module.solvePnP(
            object_points,
            image_points,
            camera_matrix,
            distortion,
        )
        if not success:
            items.append(
                {"index": index, "valid": False, "reason": "solve-pnp-failed"}
            )
            continue
        projected, _ = cv2_module.projectPoints(
            object_points,
            rotation,
            translation,
            camera_matrix,
            distortion,
        )
        residuals = np_module.linalg.norm(
            projected.reshape(-1, 2) - image_points.reshape(-1, 2),
            axis=1,
        )
        rms = float(np_module.sqrt(np_module.mean(residuals**2)))
        squared_errors.extend(float(item * item) for item in residuals)
        items.append(
            {
                "index": index,
                "valid": True,
                "rms_reprojection_error": rms,
                "maximum_reprojection_error": float(np_module.max(residuals)),
                "outlier": rms > maximum_error,
                "rotation_vector": rotation.reshape(-1).astype(float).tolist(),
                "translation_vector": translation.reshape(-1).astype(float).tolist(),
                "observed_points": image_points.reshape(-1, 2).astype(float).tolist(),
                "projected_points": projected.reshape(-1, 2).astype(float).tolist(),
                "residual_vectors": (
                    projected.reshape(-1, 2) - image_points.reshape(-1, 2)
                )
                .astype(float)
                .tolist(),
            }
        )
    overall_rms = math.sqrt(sum(squared_errors) / len(squared_errors)) if squared_errors else None
    diagnostics = {
        "format_id": "amvision.calibration-diagnostics.v1",
        "calibration_id": calibration["calibration_id"],
        "observation_count": len(observations),
        "valid_observation_count": sum(bool(item.get("valid")) for item in items),
        "outlier_indices": [
            item["index"] for item in items if item.get("outlier") is True
        ],
        "overall_rms_reprojection_error": overall_rms,
        "reported_rms_reprojection_error": calibration["rms_reprojection_error"],
        "maximum_allowed_error": maximum_error,
        "items": items,
    }
    return {"diagnostics": build_value_payload(diagnostics)}


def handle_stereo_calibrate(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """使用固定左右内参和配对观察计算双目外参、E、F 与极线误差。"""

    execution_control = build_node_execution_control(request)
    execution_control.raise_if_cancelled_or_expired()
    cv2_module, np_module = require_opencv_imports()
    left = require_camera_calibration_payload(request.input_values.get("left_camera"))
    right = require_camera_calibration_payload(request.input_values.get("right_camera"))
    if left["image_size"] != right["image_size"]:
        raise InvalidRequestError("左右 camera_calibration 的 image_size 必须一致")
    if left["object_point_unit"] != right["object_point_unit"]:
        raise InvalidRequestError("左右 camera_calibration 的 object_point_unit 必须一致")
    observations = _require_observations(request, input_name="observations")
    minimum_views = read_int(
        request.parameters.get("minimum_views"),
        field_name="minimum_views",
        default=3,
        minimum=2,
    )
    if len(observations) < minimum_views:
        raise InvalidRequestError("双目标定配对观察数量不足")
    object_points = []
    left_points = []
    right_points = []
    for observation in observations:
        execution_control.raise_if_cancelled_or_expired()
        object_item = np_module.asarray(
            _require_object_points(observation), dtype=np_module.float32
        )
        left_item = np_module.asarray(
            _require_named_image_points(observation, "left_image_points"),
            dtype=np_module.float32,
        ).reshape(-1, 1, 2)
        right_item = np_module.asarray(
            _require_named_image_points(observation, "right_image_points"),
            dtype=np_module.float32,
        ).reshape(-1, 1, 2)
        if len(object_item) != len(left_item) or len(object_item) != len(right_item):
            raise InvalidRequestError("双目标定每组 object/left/right 点数必须一致")
        object_points.append(object_item)
        left_points.append(left_item)
        right_points.append(right_item)
    left_matrix = np_module.asarray(left["camera_matrix"], dtype=np_module.float64)
    right_matrix = np_module.asarray(right["camera_matrix"], dtype=np_module.float64)
    left_distortion = np_module.asarray(left["distortion_coefficients"], dtype=np_module.float64)
    right_distortion = np_module.asarray(right["distortion_coefficients"], dtype=np_module.float64)
    result = cv2_module.stereoCalibrate(
        object_points,
        left_points,
        right_points,
        left_matrix,
        left_distortion,
        right_matrix,
        right_distortion,
        tuple(left["image_size"]),
        criteria=(
            cv2_module.TERM_CRITERIA_EPS | cv2_module.TERM_CRITERIA_COUNT,
            100,
            1e-7,
        ),
        flags=cv2_module.CALIB_FIX_INTRINSIC,
    )
    execution_control.raise_if_cancelled_or_expired()
    rms, _, _, _, _, rotation, translation, essential, fundamental = result
    epipolar_errors = _epipolar_errors(
        left_points,
        right_points,
        fundamental,
        cv2_module=cv2_module,
        np_module=np_module,
    )
    fingerprint = _fingerprint(
        {
            "left": left["source_fingerprint"],
            "right": right["source_fingerprint"],
            "observations": observations,
        }
    )
    stereo = require_stereo_calibration_payload(
        {
            "stereo_calibration_id": f"stereo-{fingerprint[:24]}",
            "left_camera": left,
            "right_camera": right,
            "image_size": left["image_size"],
            "left_coordinate_space": left["image_coordinate_space"],
            "right_coordinate_space": right["image_coordinate_space"],
            "rotation_3x3": rotation.astype(float).tolist(),
            "translation_3": translation.reshape(-1).astype(float).tolist(),
            "essential_matrix_3x3": essential.astype(float).tolist(),
            "fundamental_matrix_3x3": fundamental.astype(float).tolist(),
            "rms_epipolar_error": float(np_module.sqrt(np_module.mean(np_module.square(epipolar_errors)))),
            "source_fingerprint": fingerprint,
            "diagnostics": {
                "stereo_calibration_rms": float(rms),
                "paired_observation_count": len(observations),
                "mean_epipolar_error": float(np_module.mean(epipolar_errors)),
                "maximum_epipolar_error": float(np_module.max(epipolar_errors)),
            },
        }
    )
    return {"stereo_calibration": stereo}


def handle_stereo_rectify(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算左右校正旋转、投影矩阵、Q 和有效区域。"""

    execution_control = build_node_execution_control(request)
    execution_control.raise_if_cancelled_or_expired()
    cv2_module, np_module = require_opencv_imports()
    stereo = require_stereo_calibration_payload(
        request.input_values.get("stereo_calibration")
    )
    left = stereo["left_camera"]
    right = stereo["right_camera"]
    alpha = read_float(
        request.parameters.get("alpha"),
        field_name="alpha",
        default=-1.0,
        minimum=-1.0,
        maximum=1.0,
    )
    left_rotation, right_rotation, left_projection, right_projection, disparity_to_depth, left_roi, right_roi = (
        cv2_module.stereoRectify(
            np_module.asarray(left["camera_matrix"], dtype=np_module.float64),
            np_module.asarray(left["distortion_coefficients"], dtype=np_module.float64),
            np_module.asarray(right["camera_matrix"], dtype=np_module.float64),
            np_module.asarray(right["distortion_coefficients"], dtype=np_module.float64),
            tuple(stereo["image_size"]),
            np_module.asarray(stereo["rotation_3x3"], dtype=np_module.float64),
            np_module.asarray(stereo["translation_3"], dtype=np_module.float64),
            flags=cv2_module.CALIB_ZERO_DISPARITY,
            alpha=alpha,
        )
    )
    execution_control.raise_if_cancelled_or_expired()
    updated = dict(stereo)
    updated["rectification"] = {
        "left_rotation_3x3": left_rotation.astype(float).tolist(),
        "right_rotation_3x3": right_rotation.astype(float).tolist(),
        "left_projection_3x4": left_projection.astype(float).tolist(),
        "right_projection_3x4": right_projection.astype(float).tolist(),
        "disparity_to_depth_4x4": disparity_to_depth.astype(float).tolist(),
        "left_valid_roi_xywh": [int(item) for item in left_roi],
        "right_valid_roi_xywh": [int(item) for item in right_roi],
    }
    updated["diagnostics"] = {
        **stereo["diagnostics"],
        "rectification_alpha": alpha,
    }
    return {"stereo_calibration": require_stereo_calibration_payload(updated)}


def handle_rectification_map(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """生成左右校正 map，原子写入 ObjectStore 并返回可追溯 key。"""

    execution_control = build_node_execution_control(request)
    execution_control.raise_if_cancelled_or_expired()
    cv2_module, np_module = require_opencv_imports()
    stereo = require_stereo_calibration_payload(
        request.input_values.get("stereo_calibration")
    )
    rectification = stereo.get("rectification")
    if not isinstance(rectification, dict):
        raise InvalidRequestError("rectification-map 要求先执行 stereo-rectify")
    save_location = resolve_required_save_location_from_request(
        request,
        scope="directory",
    )
    if save_location.kind != SAVE_LOCATION_OBJECT_STORE:
        raise InvalidRequestError("rectification map 必须保存到 ObjectStore 相对位置")
    width, height = [int(item) for item in stereo["image_size"]]
    left = stereo["left_camera"]
    right = stereo["right_camera"]
    left_map_x, left_map_y = cv2_module.initUndistortRectifyMap(
        np_module.asarray(left["camera_matrix"], dtype=np_module.float64),
        np_module.asarray(left["distortion_coefficients"], dtype=np_module.float64),
        np_module.asarray(rectification["left_rotation_3x3"], dtype=np_module.float64),
        np_module.asarray(rectification["left_projection_3x4"], dtype=np_module.float64),
        (width, height),
        cv2_module.CV_32FC1,
    )
    right_map_x, right_map_y = cv2_module.initUndistortRectifyMap(
        np_module.asarray(right["camera_matrix"], dtype=np_module.float64),
        np_module.asarray(right["distortion_coefficients"], dtype=np_module.float64),
        np_module.asarray(rectification["right_rotation_3x3"], dtype=np_module.float64),
        np_module.asarray(rectification["right_projection_3x4"], dtype=np_module.float64),
        (width, height),
        cv2_module.CV_32FC1,
    )
    execution_control.raise_if_cancelled_or_expired()
    maps = {
        "left_map_x": left_map_x,
        "left_map_y": left_map_y,
        "right_map_x": right_map_x,
        "right_map_y": right_map_y,
    }
    object_keys: dict[str, str] = {}
    map_metadata: dict[str, object] = {}
    for name, matrix in maps.items():
        execution_control.raise_if_cancelled_or_expired()
        content = _serialize_numpy(matrix, np_module=np_module)
        saved = save_bytes(
            request,
            save_location=save_location,
            file_name=f"{name}.npy",
            content=content,
        )
        object_key = str(saved.object_key or "")
        object_keys[name] = object_key
        map_metadata[name] = {
            "object_key": object_key,
            "shape": list(matrix.shape),
            "dtype": str(matrix.dtype),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    updated = dict(stereo)
    updated_rectification = dict(rectification)
    updated_rectification["map_object_keys"] = object_keys
    updated["rectification"] = updated_rectification
    return {
        "stereo_calibration": require_stereo_calibration_payload(updated),
        "maps": build_value_payload(
            {
                "format_id": "amvision.rectification-maps.v1",
                "source_fingerprint": stereo["source_fingerprint"],
                "image_size": stereo["image_size"],
                "maps": map_metadata,
            }
        ),
    }


def handle_image_rectify_stereo(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """读取已生成 map 校正左右图片，不在帧路径重复计算 map。"""

    execution_control = build_node_execution_control(request)
    execution_control.raise_if_cancelled_or_expired()
    cv2_module, np_module = require_opencv_imports()
    stereo = require_stereo_calibration_payload(
        request.input_values.get("stereo_calibration")
    )
    rectification = stereo.get("rectification")
    if not isinstance(rectification, dict) or not isinstance(
        rectification.get("map_object_keys"),
        dict,
    ):
        raise InvalidRequestError("image-rectify-stereo 要求已生成 map_object_keys")
    left_payload, _, left_image = load_image_matrix(
        request,
        input_name="left_image",
        imdecode_flags=cv2_module.IMREAD_UNCHANGED,
    )
    right_payload, _, right_image = load_image_matrix(
        request,
        input_name="right_image",
        imdecode_flags=cv2_module.IMREAD_UNCHANGED,
    )
    expected_size = tuple(int(item) for item in stereo["image_size"])
    if (left_image.shape[1], left_image.shape[0]) != expected_size or (
        right_image.shape[1],
        right_image.shape[0],
    ) != expected_size:
        raise InvalidRequestError("左右图片尺寸必须与 stereo_calibration.image_size 一致")
    storage = require_dataset_storage(request)
    keys = rectification["map_object_keys"]
    loaded_maps = {
        name: np_module.load(storage.resolve(str(keys[name])), mmap_mode="r", allow_pickle=False)
        for name in ("left_map_x", "left_map_y", "right_map_x", "right_map_y")
    }
    left_rectified = cv2_module.remap(
        left_image,
        loaded_maps["left_map_x"],
        loaded_maps["left_map_y"],
        interpolation=cv2_module.INTER_LINEAR,
        borderMode=cv2_module.BORDER_CONSTANT,
    )
    execution_control.raise_if_cancelled_or_expired()
    right_rectified = cv2_module.remap(
        right_image,
        loaded_maps["right_map_x"],
        loaded_maps["right_map_y"],
        interpolation=cv2_module.INTER_LINEAR,
        borderMode=cv2_module.BORDER_CONSTANT,
    )
    execution_control.raise_if_cancelled_or_expired()
    return {
        "left_image": build_typed_output_image_matrix_payload(
            request,
            image_matrix=left_rectified,
        ),
        "right_image": build_typed_output_image_matrix_payload(
            request,
            image_matrix=right_rectified,
        ),
        "diagnostics": build_value_payload(
            {
                "stereo_calibration_id": stereo["stereo_calibration_id"],
                "source_fingerprint": stereo["source_fingerprint"],
                "left_source_image": left_payload,
                "right_source_image": right_payload,
                "map_object_keys": keys,
            }
        ),
    }


def _require_observations(
    request: WorkflowNodeExecutionRequest,
    *,
    input_name: str,
) -> list[dict[str, object]]:
    """读取 value.v1 中的观察数组。"""

    value = require_value_payload(
        request.input_values.get(input_name),
        field_name=input_name,
    )["value"]
    raw_items = value.get("items") if isinstance(value, dict) else value
    if not isinstance(raw_items, list) or not raw_items:
        raise InvalidRequestError(f"{input_name}.value 必须包含非空 items 数组")
    if not all(isinstance(item, dict) for item in raw_items):
        raise InvalidRequestError(f"{input_name}.items 每项必须是对象")
    return [dict(item) for item in raw_items]


def _require_image_points(observation: dict[str, object]) -> list[list[float]]:
    """读取单目观察 image_points。"""

    return _require_named_image_points(observation, "image_points")


def _require_named_image_points(
    observation: dict[str, object],
    field_name: str,
) -> list[list[float]]:
    """读取二维有限点数组。"""

    value = observation.get(field_name)
    if not isinstance(value, list) or len(value) < 4:
        raise InvalidRequestError(f"{field_name} 至少包含四个点")
    return _as_float_points(value)


def _require_object_points(observation: dict[str, object]) -> list[list[float]]:
    """读取三维有限物点数组。"""

    value = observation.get("object_points")
    if not isinstance(value, list) or len(value) < 4:
        raise InvalidRequestError("object_points 至少包含四个点")
    points = []
    for item in value:
        if not isinstance(item, list) or len(item) != 3:
            raise InvalidRequestError("object_points 每项必须是 [x,y,z]")
        point = [float(cell) for cell in item]
        if not all(math.isfinite(cell) for cell in point):
            raise InvalidRequestError("object_points 只能包含有限数值")
        points.append(point)
    return points


def _as_float_points(value: list[object]) -> list[list[float]]:
    """校验二维有限点数组。"""

    points: list[list[float]] = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise InvalidRequestError("image_points 每项必须是 [x,y]")
        point = [float(cell) for cell in item]
        if not all(math.isfinite(cell) for cell in point):
            raise InvalidRequestError("image_points 只能包含有限数值")
        points.append(point)
    return points


def _require_image_size(observation: dict[str, object]) -> tuple[int, int]:
    """读取观察图片尺寸。"""

    value = observation.get("image_size")
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in value)
    ):
        raise InvalidRequestError("observation.image_size 必须是正整数 [width,height]")
    return int(value[0]), int(value[1])


def _epipolar_errors(
    left_points: list[Any],
    right_points: list[Any],
    fundamental: Any,
    *,
    cv2_module: Any,
    np_module: Any,
) -> Any:
    """计算左右点到对应极线的对称距离。"""

    errors = []
    for left_item, right_item in zip(left_points, right_points, strict=True):
        left_flat = left_item.reshape(-1, 2)
        right_flat = right_item.reshape(-1, 2)
        right_lines = cv2_module.computeCorrespondEpilines(
            left_item,
            1,
            fundamental,
        ).reshape(-1, 3)
        left_lines = cv2_module.computeCorrespondEpilines(
            right_item,
            2,
            fundamental,
        ).reshape(-1, 3)
        right_distance = np_module.abs(
            right_lines[:, 0] * right_flat[:, 0]
            + right_lines[:, 1] * right_flat[:, 1]
            + right_lines[:, 2]
        ) / np_module.maximum(
            1e-12,
            np_module.linalg.norm(right_lines[:, :2], axis=1),
        )
        left_distance = np_module.abs(
            left_lines[:, 0] * left_flat[:, 0]
            + left_lines[:, 1] * left_flat[:, 1]
            + left_lines[:, 2]
        ) / np_module.maximum(
            1e-12,
            np_module.linalg.norm(left_lines[:, :2], axis=1),
        )
        errors.extend(((left_distance + right_distance) / 2.0).tolist())
    return np_module.asarray(errors, dtype=np_module.float64)


def _serialize_numpy(matrix: Any, *, np_module: Any) -> bytes:
    """序列化单个 NumPy map 为禁止 pickle 的 .npy bytes。"""

    stream = BytesIO()
    np_module.save(stream, matrix, allow_pickle=False)
    return stream.getvalue()


def _fingerprint(payload: object) -> str:
    """对 JSON 结构生成稳定 SHA-256。"""

    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


INDUSTRIAL_CALIBRATION_NODE_HANDLERS = (
    (OBSERVATION_FILTER_NODE_TYPE_ID, handle_observation_filter),
    (CALIBRATION_DIAGNOSE_NODE_TYPE_ID, handle_calibration_diagnose),
    (STEREO_CALIBRATE_NODE_TYPE_ID, handle_stereo_calibrate),
    (STEREO_RECTIFY_NODE_TYPE_ID, handle_stereo_rectify),
    (RECTIFICATION_MAP_NODE_TYPE_ID, handle_rectification_map),
    (IMAGE_RECTIFY_STEREO_NODE_TYPE_ID, handle_image_rectify_stereo),
)


__all__ = ["INDUSTRIAL_CALIBRATION_NODE_HANDLERS"]
