"""通用特征定位与边缘形状定位节点。"""

from __future__ import annotations

import math
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.execution_control import (
    build_node_execution_control,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    read_choice,
    read_float,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads import (
    build_localizations_payload,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.transforms import (
    build_planar_transform_payload,
)

FEATURE_LOCATE_NODE_TYPE_ID = "custom.opencv.feature-locate"
SHAPE_LOCATE_NODE_TYPE_ID = "custom.opencv.shape-locate"


def handle_feature_locate(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """提取局部特征、匹配、RANSAC 验证并输出统一定位结果。"""

    cv2_module, np_module = require_opencv_imports()
    source_payload, _, source = load_image_matrix(
        request,
        input_name="image",
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    template_payload, _, template = load_image_matrix(
        request,
        input_name="template_image",
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    detector_name = read_choice(
        request.parameters.get("detector"),
        field_name="detector",
        choices={"orb", "akaze", "sift"},
        default="orb",
    )
    max_features = read_int(
        request.parameters.get("max_features"),
        field_name="max_features",
        default=1500,
        minimum=16,
        maximum=20000,
    )
    detector, norm_type = _create_detector(
        detector_name,
        max_features=max_features,
        cv2_module=cv2_module,
    )
    template_keypoints, template_descriptors = detector.detectAndCompute(template, None)
    source_keypoints, source_descriptors = detector.detectAndCompute(source, None)
    if template_descriptors is None or len(template_keypoints) < 4:
        raise InvalidRequestError("template_image 可用特征不足")
    if source_descriptors is None or len(source_keypoints) < 4:
        raise InvalidRequestError("image 可用特征不足")
    matcher = cv2_module.BFMatcher(norm_type, crossCheck=False)
    raw_matches = matcher.knnMatch(template_descriptors, source_descriptors, k=2)
    ratio_threshold = read_float(
        request.parameters.get("ratio_threshold"),
        field_name="ratio_threshold",
        default=0.75,
        minimum=0.01,
        maximum=1.0,
    )
    good_matches = [
        first
        for pair in raw_matches
        if len(pair) == 2
        for first, second in [pair]
        if first.distance < ratio_threshold * second.distance
    ]
    minimum_matches = read_int(
        request.parameters.get("minimum_matches"),
        field_name="minimum_matches",
        default=8,
        minimum=4,
        maximum=10000,
    )
    if len(good_matches) < minimum_matches:
        raise InvalidRequestError(
            "feature-locate 通过 ratio test 的匹配不足",
            details={"match_count": len(good_matches), "minimum_matches": minimum_matches},
        )
    source_points = np_module.float32(
        [template_keypoints[match.queryIdx].pt for match in good_matches]
    ).reshape(-1, 1, 2)
    target_points = np_module.float32(
        [source_keypoints[match.trainIdx].pt for match in good_matches]
    ).reshape(-1, 1, 2)
    ransac_threshold = read_float(
        request.parameters.get("ransac_reprojection_threshold"),
        field_name="ransac_reprojection_threshold",
        default=3.0,
        minimum=0.01,
    )
    homography, inlier_mask = cv2_module.findHomography(
        source_points,
        target_points,
        cv2_module.RANSAC,
        ransac_threshold,
    )
    if homography is None or inlier_mask is None:
        raise InvalidRequestError("feature-locate 无法估计稳定 Homography")
    inlier_flags = inlier_mask.reshape(-1).astype(bool)
    inlier_count = int(np_module.count_nonzero(inlier_flags))
    if inlier_count < minimum_matches:
        raise InvalidRequestError(
            "feature-locate RANSAC 内点不足",
            details={"inlier_count": inlier_count, "minimum_matches": minimum_matches},
        )
    inverse = np_module.linalg.inv(homography)
    projected = cv2_module.perspectiveTransform(source_points, homography)
    reprojection = np_module.linalg.norm(
        projected.reshape(-1, 2) - target_points.reshape(-1, 2),
        axis=1,
    )
    reprojection_error = float(np_module.mean(reprojection[inlier_flags]))
    transform = build_planar_transform_payload(
        matrix_3x3=homography.tolist(),
        inverse_matrix_3x3=inverse.tolist(),
        source_coordinate_space="template-image-pixels",
        target_coordinate_space="source-image-pixels",
        match_count=len(good_matches),
        inlier_count=inlier_count,
        inlier_match_ids=[
            f"feature-match-{index + 1}"
            for index, is_inlier in enumerate(inlier_flags)
            if is_inlier
        ],
        reprojection_error=reprojection_error,
        source_a_image=template_payload,
        source_b_image=source_payload,
    )
    center, angle_degrees, scale, polygon = _localization_geometry(
        homography,
        width=int(template.shape[1]),
        height=int(template.shape[0]),
        cv2_module=cv2_module,
        np_module=np_module,
    )
    score = min(1.0, inlier_count / max(minimum_matches, len(good_matches)))
    localizations = build_localizations_payload(
        items=[
            {
                "localization_id": "feature-location-1",
                "method": f"feature-{detector_name}-homography",
                "center_xy": center,
                "angle_degrees": angle_degrees,
                "scale": scale,
                "score": score,
                "transform": transform,
                "region": {"polygon_xy": polygon},
                "diagnostics": {
                    "template_keypoint_count": len(template_keypoints),
                    "source_keypoint_count": len(source_keypoints),
                    "ratio_match_count": len(good_matches),
                    "inlier_count": inlier_count,
                    "inlier_ratio": inlier_count / len(good_matches),
                    "reprojection_error": reprojection_error,
                },
            }
        ],
        coordinate_space="source-image-pixels",
        source_image=source_payload,
        reference_image=template_payload,
    )
    return {"localizations": localizations, "transform": transform}


def handle_shape_locate(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """在离散角度和尺度范围内进行边缘形状模板定位。"""

    cv2_module, np_module = require_opencv_imports()
    source_payload, _, source = load_image_matrix(
        request,
        input_name="image",
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    template_payload, _, template = load_image_matrix(
        request,
        input_name="template_image",
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    canny_low = read_float(
        request.parameters.get("canny_low_threshold"),
        field_name="canny_low_threshold",
        default=50.0,
        minimum=0.0,
        maximum=255.0,
    )
    canny_high = read_float(
        request.parameters.get("canny_high_threshold"),
        field_name="canny_high_threshold",
        default=150.0,
        minimum=0.0,
        maximum=255.0,
    )
    if canny_high < canny_low:
        raise InvalidRequestError("canny_high_threshold 必须大于等于 canny_low_threshold")
    source_edges = cv2_module.Canny(source, canny_low, canny_high)
    template_edges = cv2_module.Canny(template, canny_low, canny_high)
    angle_values = _inclusive_range(
        read_float(request.parameters.get("angle_min"), field_name="angle_min", default=0.0),
        read_float(request.parameters.get("angle_max"), field_name="angle_max", default=0.0),
        read_float(request.parameters.get("angle_step"), field_name="angle_step", default=1.0, minimum=0.01),
    )
    scale_values = _inclusive_range(
        read_float(request.parameters.get("scale_min"), field_name="scale_min", default=1.0, minimum=0.01),
        read_float(request.parameters.get("scale_max"), field_name="scale_max", default=1.0, minimum=0.01),
        read_float(request.parameters.get("scale_step"), field_name="scale_step", default=0.1, minimum=0.001),
    )
    if len(angle_values) * len(scale_values) > 512:
        raise InvalidRequestError("shape-locate 角度与尺度组合不能超过 512")
    execution_control = build_node_execution_control(request)
    best: tuple[float, tuple[int, int], Any, Any, float, float] | None = None
    for scale in scale_values:
        for angle in angle_values:
            execution_control.raise_if_cancelled_or_expired()
            transformed, original_to_variant = _rotate_scale_template(
                template_edges,
                angle_degrees=angle,
                scale=scale,
                cv2_module=cv2_module,
                np_module=np_module,
            )
            if (
                transformed.shape[0] > source_edges.shape[0]
                or transformed.shape[1] > source_edges.shape[1]
                or transformed.shape[0] < 2
                or transformed.shape[1] < 2
            ):
                continue
            result = cv2_module.matchTemplate(
                source_edges,
                transformed,
                cv2_module.TM_CCOEFF_NORMED,
            )
            _, maximum, _, location = cv2_module.minMaxLoc(result)
            if best is None or float(maximum) > best[0]:
                best = (
                    float(maximum),
                    (int(location[0]), int(location[1])),
                    transformed,
                    original_to_variant,
                    angle,
                    scale,
                )
    if best is None:
        raise InvalidRequestError("shape-locate 搜索范围内没有可用模板")
    score, location, _, original_to_variant, angle, scale = best
    minimum_score = read_float(
        request.parameters.get("minimum_score"),
        field_name="minimum_score",
        default=0.5,
        minimum=-1.0,
        maximum=1.0,
    )
    if score < minimum_score:
        raise InvalidRequestError(
            "shape-locate 最佳分数低于 minimum_score",
            details={"score": score, "minimum_score": minimum_score},
        )
    translation = np_module.asarray(
        [[1.0, 0.0, location[0]], [0.0, 1.0, location[1]], [0.0, 0.0, 1.0]],
        dtype=np_module.float64,
    )
    homography = translation @ original_to_variant
    inverse = np_module.linalg.inv(homography)
    transform = build_planar_transform_payload(
        matrix_3x3=homography.tolist(),
        inverse_matrix_3x3=inverse.tolist(),
        source_coordinate_space="template-image-pixels",
        target_coordinate_space="source-image-pixels",
        match_count=1,
        inlier_count=1,
        inlier_match_ids=["shape-match-1"],
        reprojection_error=None,
        source_a_image=template_payload,
        source_b_image=source_payload,
        transform_kind="similarity",
    )
    center, resolved_angle, resolved_scale, polygon = _localization_geometry(
        homography,
        width=int(template.shape[1]),
        height=int(template.shape[0]),
        cv2_module=cv2_module,
        np_module=np_module,
    )
    normalized_score = max(0.0, min(1.0, (score + 1.0) / 2.0))
    localizations = build_localizations_payload(
        items=[
            {
                "localization_id": "shape-location-1",
                "method": "edge-shape-template",
                "center_xy": center,
                "angle_degrees": resolved_angle,
                "scale": resolved_scale,
                "score": normalized_score,
                "transform": transform,
                "region": {"polygon_xy": polygon},
                "diagnostics": {
                    "raw_correlation_score": score,
                    "search_angle_degrees": angle,
                    "search_scale": scale,
                    "candidate_count": len(angle_values) * len(scale_values),
                },
            }
        ],
        coordinate_space="source-image-pixels",
        source_image=source_payload,
        reference_image=template_payload,
    )
    return {"localizations": localizations, "transform": transform}


def _create_detector(name: str, *, max_features: int, cv2_module: Any) -> tuple[Any, int]:
    """创建稳定的局部特征 detector 与匹配距离。"""

    if name == "orb":
        return cv2_module.ORB_create(nfeatures=max_features), cv2_module.NORM_HAMMING
    if name == "akaze":
        return cv2_module.AKAZE_create(), cv2_module.NORM_HAMMING
    return cv2_module.SIFT_create(nfeatures=max_features), cv2_module.NORM_L2


def _localization_geometry(
    homography: Any,
    *,
    width: int,
    height: int,
    cv2_module: Any,
    np_module: Any,
) -> tuple[list[float], float, float, list[list[float]]]:
    """从模板到目标 Homography 计算中心、角度、尺度和四角。"""

    corners = np_module.float32(
        [[[0.0, 0.0], [float(width), 0.0], [float(width), float(height)], [0.0, float(height)]]]
    )
    projected = cv2_module.perspectiveTransform(corners, homography)[0]
    center_point = np_module.float32([[[width / 2.0, height / 2.0]]])
    center = cv2_module.perspectiveTransform(center_point, homography)[0, 0]
    first_edge = projected[1] - projected[0]
    scale = float(np_module.linalg.norm(first_edge) / max(1.0, float(width)))
    if not math.isfinite(scale) or scale <= 0:
        raise InvalidRequestError("定位变换得到无效 scale")
    angle = math.degrees(math.atan2(float(first_edge[1]), float(first_edge[0])))
    return (
        [float(center[0]), float(center[1])],
        angle,
        scale,
        projected.astype(float).round(6).tolist(),
    )


def _inclusive_range(minimum: float, maximum: float, step: float) -> list[float]:
    """生成包含终点且数量有界的浮点搜索序列。"""

    if maximum < minimum:
        raise InvalidRequestError("搜索范围 maximum 必须大于等于 minimum")
    count = int(math.floor((maximum - minimum) / step + 1e-9)) + 1
    return [minimum + index * step for index in range(count)]


def _rotate_scale_template(
    template: Any,
    *,
    angle_degrees: float,
    scale: float,
    cv2_module: Any,
    np_module: Any,
) -> tuple[Any, Any]:
    """旋转缩放模板并返回原图到变体图的 3x3 矩阵。"""

    height, width = int(template.shape[0]), int(template.shape[1])
    center = (width / 2.0, height / 2.0)
    affine = cv2_module.getRotationMatrix2D(center, angle_degrees, scale)
    cosine = abs(float(affine[0, 0]))
    sine = abs(float(affine[0, 1]))
    output_width = max(1, int(math.ceil(height * sine + width * cosine)))
    output_height = max(1, int(math.ceil(height * cosine + width * sine)))
    affine[0, 2] += output_width / 2.0 - center[0]
    affine[1, 2] += output_height / 2.0 - center[1]
    transformed = cv2_module.warpAffine(
        template,
        affine,
        (output_width, output_height),
        flags=cv2_module.INTER_NEAREST,
        borderMode=cv2_module.BORDER_CONSTANT,
        borderValue=0,
    )
    matrix = np_module.vstack([affine, [0.0, 0.0, 1.0]]).astype(np_module.float64)
    return transformed, matrix


INDUSTRIAL_LOCALIZATION_NODE_HANDLERS = (
    (FEATURE_LOCATE_NODE_TYPE_ID, handle_feature_locate),
    (SHAPE_LOCATE_NODE_TYPE_ID, handle_shape_locate),
)


__all__ = ["INDUSTRIAL_LOCALIZATION_NODE_HANDLERS"]
