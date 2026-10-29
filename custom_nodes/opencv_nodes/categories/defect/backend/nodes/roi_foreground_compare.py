"""在共同坐标系内逐 ROI 比较前景，输出二维差异，不推断产品类别或高度。"""

import math

import cv2
import numpy as np

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.region import build_regions_payload
from backend.nodes.core_nodes.support.roi import require_roi_list_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.execution_control import (
    build_node_execution_control,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    read_choice,
    read_float,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import (
    load_image_matrix,
    build_output_image_matrix_payload,
)

NODE_TYPE_ID = "custom.opencv.roi-foreground-compare"


def compare_foreground(
    image,
    reference,
    *,
    threshold,
    polarity,
    tolerance_pixels,
    domain=None,
    visualization=None,
):
    """比较同尺寸灰度图；容差采用像素邻域，不平移、旋转或修改输入。"""
    current = image <= threshold if polarity == "dark" else image > threshold
    expected = reference <= threshold if polarity == "dark" else reference > threshold
    if domain is not None:
        current &= domain
        expected &= domain
    current_area, reference_area = int(current.sum()), int(expected.sum())
    if tolerance_pixels:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (2 * tolerance_pixels + 1,) * 2
        )
        current_near = cv2.dilate(current.astype(np.uint8), kernel) != 0
        reference_near = cv2.dilate(expected.astype(np.uint8), kernel) != 0
    else:
        current_near, reference_near = current, expected
    missing = int(np.count_nonzero(expected & ~current_near))
    excess = int(np.count_nonzero(current & ~reference_near))
    intersection, union = (
        int(np.count_nonzero(current & expected)),
        int(np.count_nonzero(current | expected)),
    )
    current_pose, reference_pose = _foreground_pose(current), _foreground_pose(expected)
    shift, angle = None, None
    if current_pose is not None and reference_pose is not None:
        shift = float(
            np.linalg.norm(
                np.array(current_pose["center_xy"]) - reference_pose["center_xy"]
            )
        )
        if (
            current_pose["axis_angle_degrees"] is not None
            and reference_pose["axis_angle_degrees"] is not None
        ):
            angle = abs(
                (
                    current_pose["axis_angle_degrees"]
                    - reference_pose["axis_angle_degrees"]
                    + 90
                )
                % 180
                - 90
            )
    if visualization is not None:
        visualization[:] = 235
        visualization[current & reference_near] = (86, 122, 8)  # BGR 绿色：匹配前景。
        visualization[expected & ~current_near] = (68, 68, 224)  # 红色：参考前景缺失。
        visualization[current & ~reference_near] = (0, 139, 217)  # 橙色：当前前景溢出。
    return {
        "reference_area": reference_area,
        "current_area": current_area,
        "missing_pixels": missing,
        "excess_pixels": excess,
        # 两种偏差都以参考面积为分母，空当前图不能产生除零或误通过。
        "missing_ratio": missing / reference_area if reference_area else None,
        "excess_ratio": excess / reference_area if reference_area else None,
        "iou": intersection / union if union else None,
        "centroid_shift_pixels": shift,
        "axis_angle_difference_degrees": angle,
        "current_pose": current_pose,
        "reference_pose": reference_pose,
    }


def _foreground_pose(mask):
    """计算前景质心和无向主轴；近圆形前景不返回不稳定的主轴角。"""
    moments = cv2.moments(mask.astype(np.uint8), binaryImage=True)
    area = moments["m00"]
    if area < 2:
        return None
    center = [moments["m10"] / area, moments["m01"] / area]
    covariance = (
        np.array(
            [[moments["mu20"], moments["mu11"]], [moments["mu11"], moments["mu02"]]]
        )
        / area
    )
    values, vectors = np.linalg.eigh(covariance)
    anisotropy = float((values[1] - values[0]) / max(values[1], 1e-12))
    angle = (
        float(np.degrees(np.arctan2(vectors[1, 1], vectors[0, 1])))
        if anisotropy >= 0.1
        else None
    )
    return {
        "center_xy": center,
        "axis_angle_degrees": angle,
        "axis_anisotropy": anisotropy,
    }


def handle_node(request):
    """读取两张已配准图和显式 ROI，逐区域分配掩膜并保留稳定 roi_id。"""
    control = build_node_execution_control(request)
    control.raise_if_cancelled_or_expired()
    payload, _, image = load_image_matrix(request, imdecode_flags=cv2.IMREAD_GRAYSCALE)
    reference_payload, _, reference = load_image_matrix(
        request, input_name="reference_image", imdecode_flags=cv2.IMREAD_GRAYSCALE
    )
    if (
        image.shape != reference.shape
        or image.dtype != np.uint8
        or reference.dtype != np.uint8
    ):
        raise InvalidRequestError(
            "ROI Foreground Compare 要求相同尺寸的 uint8 图像；先显式配准或缩放"
        )
    p = request.parameters
    threshold = read_float(
        p.get("threshold"), field_name="threshold", default=80, minimum=0, maximum=255
    )
    polarity = read_choice(
        p.get("foreground"),
        field_name="foreground",
        choices=("dark", "light"),
        default="dark",
    )
    tolerance = read_int(
        p.get("tolerance_pixels"),
        field_name="tolerance_pixels",
        default=2,
        minimum=0,
        maximum=64,
    )
    minimum = read_int(
        p.get("min_reference_area"),
        field_name="min_reference_area",
        default=100,
        minimum=1,
    )
    limits = {
        key: read_float(p.get(key), field_name=key, default=0.05, minimum=0, maximum=1)
        for key in ("max_missing_ratio", "max_excess_ratio")
    }
    check_pose = p.get("check_pose", False)
    emit_images = p.get("emit_comparison_images", False)
    if not isinstance(check_pose, bool) or not isinstance(emit_images, bool):
        raise InvalidRequestError("check_pose / emit_comparison_images 必须是布尔值")
    shift_limit = read_float(
        p.get("max_centroid_shift_pixels"),
        field_name="max_centroid_shift_pixels",
        default=8,
        minimum=0,
    )
    angle_limit = read_float(
        p.get("max_axis_angle_degrees"),
        field_name="max_axis_angle_degrees",
        default=3,
        minimum=0,
        maximum=90,
    )
    check_boundary = p.get("check_boundary", False)
    if not isinstance(check_boundary, bool):
        raise InvalidRequestError("check_boundary 必须是布尔值")
    margin = read_int(
        p.get("search_margin_pixels"),
        field_name="search_margin_pixels",
        default=8,
        minimum=1,
        maximum=128,
    )
    outside_limit = read_float(
        p.get("max_outside_ratio"),
        field_name="max_outside_ratio",
        default=0.02,
        minimum=0,
        maximum=1,
    )
    if check_boundary and margin <= tolerance:
        raise InvalidRequestError("边界搜索余量必须大于边缘容差")
    rois = require_roi_list_payload(request.input_values.get("rois"))["items"]
    if not rois or len(rois) > 1024 or len({r["roi_id"] for r in rois}) != len(rois):
        raise InvalidRequestError("ROI 列表必须含 1–1024 个不重复的 roi_id")
    height, width = image.shape
    items, regions, comparison_images = [], [], []
    for roi in rois:
        control.raise_if_cancelled_or_expired()
        if roi["roi_kind"] not in {"bbox", "polygon"}:
            raise InvalidRequestError("ROI Foreground Compare 支持 bbox / polygon ROI")
        if not all(math.isfinite(v) for v in roi["bbox_xyxy"]):
            raise InvalidRequestError("ROI bbox 必须是有限数值")
        x1, y1 = (math.floor(v) for v in roi["bbox_xyxy"][:2])
        x2, y2 = (math.ceil(v) for v in roi["bbox_xyxy"][2:])
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise InvalidRequestError(
                "ROI 超出图像，不能静默裁剪", details={"roi_id": roi["roi_id"]}
            )
        # 边界检查时，显式扩大观察范围；原 ROI 仍是允许区域，禁止先裁掉越界像素。
        allowed_domain = None
        if check_boundary:
            x1, y1, x2, y2 = x1 - margin, y1 - margin, x2 + margin, y2 + margin
            if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                raise InvalidRequestError(
                    "边界检查的搜索余量超出图片", details={"roi_id": roi["roi_id"]}
                )
            allowed_domain = np.zeros((y2 - y1, x2 - x1), np.uint8)
            vertices = np.asarray(roi["polygon_xy"], dtype=np.float64)
            if (
                not np.isfinite(vertices).all()
                or np.any(vertices < roi["bbox_xyxy"][:2])
                or np.any(vertices > roi["bbox_xyxy"][2:])
            ):
                raise InvalidRequestError("ROI 多边形顶点超出 bbox")
            cv2.fillPoly(
                allowed_domain, [np.rint(vertices - [x1, y1]).astype(np.int32)], 1
            )
        # 多边形域显式排除相邻物体；域外变化不属于该 ROI 的判定范围。
        domain = None
        if check_boundary:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * margin + 1,) * 2)
            domain = cv2.dilate(allowed_domain, kernel) != 0
        elif roi["roi_kind"] == "polygon":
            vertices = np.asarray(roi["polygon_xy"], dtype=np.float64)
            if (
                not np.isfinite(vertices).all()
                or np.any(vertices < [x1, y1])
                or np.any(vertices > [x2, y2])
            ):
                raise InvalidRequestError("ROI 多边形顶点超出 bbox")
            domain = np.zeros((y2 - y1, x2 - x1), dtype=np.uint8)
            cv2.fillPoly(domain, [np.rint(vertices - [x1, y1]).astype(np.int32)], 1)
            domain = domain != 0
        # 掩膜仅在本区域内生成，不为每个 ROI 分配整图掩膜。
        visual = np.empty((y2 - y1, x2 - x1, 3), np.uint8) if emit_images else None
        metrics = compare_foreground(
            image[y1:y2, x1:x2],
            reference[y1:y2, x1:x2],
            threshold=threshold,
            polarity=polarity,
            tolerance_pixels=tolerance,
            domain=domain,
            visualization=visual,
        )
        boundary_passed, reference_boundary_valid = None, True
        if check_boundary:
            current_gray, reference_gray = image[y1:y2, x1:x2], reference[y1:y2, x1:x2]
            allowed_near = allowed_domain
            if tolerance:
                allowed_near = cv2.dilate(
                    allowed_domain,
                    cv2.getStructuringElement(
                        cv2.MORPH_ELLIPSE, (2 * tolerance + 1,) * 2
                    ),
                )
            outside_domain = domain & (allowed_near == 0)
            outside = outside_domain & (
                current_gray <= threshold
                if polarity == "dark"
                else current_gray > threshold
            )
            reference_outside = outside_domain & (
                reference_gray <= threshold
                if polarity == "dark"
                else reference_gray > threshold
            )
            outside_count, reference_outside_count = (
                int(outside.sum()),
                int(reference_outside.sum()),
            )
            outside_ratio = (
                outside_count / metrics["current_area"]
                if metrics["current_area"]
                else None
            )
            reference_outside_ratio = (
                reference_outside_count / metrics["reference_area"]
                if metrics["reference_area"]
                else None
            )
            reference_boundary_valid = (
                reference_outside_ratio is not None
                and reference_outside_ratio <= outside_limit
            )
            boundary_passed = (
                reference_boundary_valid
                and outside_ratio is not None
                and outside_ratio <= outside_limit
            )
            metrics.update(
                outside_pixels=outside_count,
                outside_ratio=outside_ratio,
                reference_outside_ratio=reference_outside_ratio,
                allowed_roi={
                    key: roi[key]
                    for key in ("roi_id", "roi_kind", "bbox_xyxy", "polygon_xy", "area")
                },
                search_bbox_xyxy=[x1, y1, x2, y2],
                pose_origin_xy=[x1, y1],
            )
            if visual is not None:
                visual[outside] = (180, 40, 200)
                cv2.polylines(
                    visual,
                    [np.rint(vertices - [x1, y1]).astype(np.int32)],
                    True,
                    (60, 60, 60),
                    1,
                )
        valid = metrics["reference_area"] >= minimum
        valid = valid and reference_boundary_valid
        shape_passed = (
            valid
            and metrics["missing_ratio"] <= limits["max_missing_ratio"]
            and metrics["excess_ratio"] <= limits["max_excess_ratio"]
        )
        pose_passed = (
            (
                valid
                and metrics["centroid_shift_pixels"] is not None
                and metrics["axis_angle_difference_degrees"] is not None
                and metrics["centroid_shift_pixels"] <= shift_limit
                and metrics["axis_angle_difference_degrees"] <= angle_limit
            )
            if check_pose
            else None
        )
        passed = (
            shape_passed
            and (pose_passed is not False)
            and (boundary_passed is not False)
        )
        reasons = []
        if not valid:
            reasons.append("invalid_reference")
            if not reference_boundary_valid:
                reasons.append("reference_outside_allowed_roi")
        else:
            if boundary_passed is False:
                reasons.append("foreground_outside_allowed_roi")
            if metrics["missing_ratio"] > limits["max_missing_ratio"]:
                reasons.append("foreground_missing")
            if metrics["excess_ratio"] > limits["max_excess_ratio"]:
                reasons.append("foreground_outside_reference")
            if check_pose:
                if (
                    metrics["centroid_shift_pixels"] is None
                    or metrics["axis_angle_difference_degrees"] is None
                ):
                    reasons.append("pose_unavailable")
                else:
                    if metrics["centroid_shift_pixels"] > shift_limit:
                        reasons.append("centroid_displaced")
                    if metrics["axis_angle_difference_degrees"] > angle_limit:
                        reasons.append("axis_rotated")
        state = (
            "invalid_reference"
            if not valid
            else ("within_tolerance" if passed else "outside_tolerance")
        )
        items.append(
            {
                "item_id": roi["roi_id"],
                "source": {
                    "roi_id": roi["roi_id"],
                    "roi_kind": roi["roi_kind"],
                    "bbox_xyxy": roi["bbox_xyxy"],
                    "polygon_xy": roi["polygon_xy"],
                },
                "result": {
                    **metrics,
                    "state": state,
                    "passed": passed,
                    "shape_passed": shape_passed,
                    "pose_passed": pose_passed,
                    "boundary_passed": boundary_passed,
                    "reasons": reasons,
                },
            }
        )
        if visual is not None:
            comparison_image = build_output_image_matrix_payload(
                request,
                source_payload=payload,
                image_matrix=visual,
                save_location=None,
                variant_name=f"comparison-{len(comparison_images) + 1}",
            )
            comparison_image.update(
                roi_id=roi["roi_id"],
                crop_index=len(comparison_images) + 1,
                bbox_xyxy=[x1, y1, x2, y2],
                comparison_state=state,
            )
            comparison_images.append(comparison_image)
        regions.append(
            {
                "region_id": roi["roi_id"],
                "class_id": 0 if passed else 1,
                "class_name": state,
                "score": 1.0,
                # 判定标记属于原 ROI；搜索余量仅用于观察，不改变结果几何。
                "bbox_xyxy": roi["bbox_xyxy"],
                "polygon_xy": roi["polygon_xy"] if roi["roi_kind"] == "polygon" else [],
                "area": roi["area"],
            }
        )
    summary = {
        "format_id": "amvision.roi-foreground-comparison.v1",
        "count": len(items),
        "passed": all(i["result"]["passed"] for i in items),
        "coordinate_space": "input-image-pixels",
        "image_size": [width, height],
        "reference_image_size": [
            reference_payload["width"],
            reference_payload["height"],
        ],
        "rules": {
            "threshold": threshold,
            "foreground": polarity,
            "tolerance_pixels": tolerance,
            "min_reference_area": minimum,
            **limits,
            "check_pose": check_pose,
            "max_centroid_shift_pixels": shift_limit,
            "max_axis_angle_degrees": angle_limit,
            "check_boundary": check_boundary,
            "search_margin_pixels": margin,
            "max_outside_ratio": outside_limit,
        },
        "items": items,
    }
    return {
        "summary": build_value_payload(summary),
        "comparison_images": {
            "items": comparison_images,
            "count": len(comparison_images),
        },
        "regions": build_regions_payload(
            source_image=payload, selected_frame_index=None, items=regions
        ),
    }
