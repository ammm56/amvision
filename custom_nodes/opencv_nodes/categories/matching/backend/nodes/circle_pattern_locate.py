"""由带名称的参考圆心图案配准候选圆；只允许刚性变换，不依赖列表顺序。"""

import math
from typing import Annotated

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, ValidationError

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.execution_control import (
    build_node_execution_control,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads.circles import (
    require_circles_payload,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.transforms import (
    build_planar_transform_payload,
)

NODE_TYPE_ID = "custom.opencv.circle-pattern-locate"


class ReferencePoint(BaseModel):
    """参考点名称和坐标；名称负责关联，数组顺序不参与匹配。"""

    model_config = ConfigDict(extra="forbid")
    point_id: Annotated[str, Field(min_length=1, max_length=128)]
    center_xy: tuple[FiniteFloat, FiniteFloat]


class Settings(BaseModel):
    """以候选圆输入图像的像素为单位设置搜索边界与配准门槛。"""

    model_config = ConfigDict(extra="forbid")
    reference_points: Annotated[
        list[ReferencePoint], Field(min_length=3, max_length=64)
    ]
    match_tolerance_px: Annotated[FiniteFloat, Field(gt=0, le=100)] = 8
    maximum_rmse_px: Annotated[FiniteFloat, Field(gt=0, le=100)] = 2
    minimum_match_ratio: Annotated[FiniteFloat, Field(gt=0, le=1)] = 0.9
    maximum_angle_degrees: Annotated[FiniteFloat, Field(ge=0, le=180)] = 10
    maximum_translation_px: Annotated[FiniteFloat, Field(gt=0)] = 500
    maximum_hypotheses: Annotated[int, Field(ge=1, le=50000)] = 5000


def _map(points, matrix):
    """将二维行向量点集投影到当前坐标。"""
    return points @ matrix[:2, :2].T + matrix[:2, 2]


def _fit(reference, observed):
    """通过 SVD 最小二乘求旋转和平移，明确排除镜像与缩放。"""
    a, b = reference.mean(axis=0), observed.mean(axis=0)
    u, _, vt = np.linalg.svd((reference - a).T @ (observed - b))
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1] *= -1
        rotation = vt.T @ u.T
    matrix = np.eye(3)
    matrix[:2, :2] = rotation
    matrix[:2, 2] = b - rotation @ a
    return matrix


def _matches(reference, observed, matrix, tolerance):
    """最近点必须一对一；发生竞争时不把同一个候选圆分配给多个参考点。"""
    distances = np.linalg.norm(
        _map(reference, matrix)[:, None] - observed[None], axis=2
    )
    indices = distances.argmin(axis=1)
    accepted = distances[np.arange(len(reference)), indices] <= tolerance
    unique, counts = np.unique(indices[accepted], return_counts=True)
    accepted &= np.isin(indices, unique[counts == 1])
    return np.flatnonzero(accepted), indices[accepted]


def locate_pattern(reference, observed, settings, *, check=lambda: None):
    """穷举有界长基线假设，再验证整个图案；多个可用位姿直接拒绝。"""
    reference = np.asarray(reference, dtype=np.float64)
    observed = np.asarray(observed, dtype=np.float64)
    needed = max(3, math.ceil(len(reference) * settings.minimum_match_ratio))
    if len(observed) < needed:
        raise ValueError("圆心图案匹配不足")
    if observed.shape != (len(observed), 2) or not np.isfinite(observed).all():
        raise ValueError("候选圆心必须为有限二维坐标")
    if np.linalg.matrix_rank(reference - reference.mean(axis=0)) < 2:
        raise ValueError("参考圆心不能共线")
    separation = np.linalg.norm(reference[:, None] - reference[None], axis=2)
    if np.any(
        separation[np.triu_indices(len(reference), 1)]
        <= settings.match_tolerance_px * 2
    ):
        raise ValueError("参考圆心间距必须大于两倍匹配容差")
    oi, oj = np.nonzero(~np.eye(len(observed), dtype=bool))
    vectors = observed[oj] - observed[oi]
    lengths = np.linalg.norm(vectors, axis=1)
    angles = np.arctan2(vectors[:, 1], vectors[:, 0])
    seen, candidates, hypotheses = set(), [], 0
    tolerance = settings.match_tolerance_px

    def within_limits(matrix):
        """拟合前后均检查本次声明的位姿范围。"""
        angle = math.degrees(math.atan2(matrix[1, 0], matrix[0, 0]))
        return (
            abs(angle) <= settings.maximum_angle_degrees + 1e-8
            and np.linalg.norm(matrix[:2, 2]) <= settings.maximum_translation_px
        )

    for i, j in zip(*np.triu_indices(len(reference), 1)):
        if separation[i, j] < separation.max() * 0.5:
            continue
        check()
        vector = reference[j] - reference[i]
        rotations = (angles - math.atan2(vector[1], vector[0]) + np.pi) % (
            2 * np.pi
        ) - np.pi
        eligible = (abs(lengths - separation[i, j]) <= 2 * tolerance) & (
            abs(rotations) <= math.radians(settings.maximum_angle_degrees) + 1e-8
        )
        for k in np.flatnonzero(eligible):
            angle = rotations[k]
            matrix = np.eye(3)
            matrix[:2, :2] = [
                [math.cos(angle), -math.sin(angle)],
                [math.sin(angle), math.cos(angle)],
            ]
            matrix[:2, 2] = observed[oi[k]] - matrix[:2, :2] @ reference[i]
            if not within_limits(matrix):
                continue
            hypotheses += 1
            if hypotheses > settings.maximum_hypotheses:
                raise ValueError("圆心配准假设超过上限，请收紧搜索范围")
            ri, ci = _matches(reference, observed, matrix, tolerance)
            if len(ri) < needed:
                continue
            key = tuple(zip(ri.tolist(), ci.tolist()))
            if key in seen:
                continue
            seen.add(key)
            for _ in range(3):
                if len(ri) < needed:
                    break
                matrix = _fit(reference[ri], observed[ci])
                ri, ci = _matches(reference, observed, matrix, tolerance)
            if len(ri) < needed or not within_limits(matrix):
                continue
            if np.linalg.matrix_rank(reference[ri] - reference[ri].mean(axis=0)) < 2:
                continue
            matrix = _fit(reference[ri], observed[ci])
            errors = np.linalg.norm(_map(reference[ri], matrix) - observed[ci], axis=1)
            rmse = float(np.sqrt(np.mean(errors**2)))
            if (
                not within_limits(matrix)
                or rmse > settings.maximum_rmse_px
                or errors.max() > tolerance
            ):
                continue
            if any(
                np.max(
                    np.linalg.norm(
                        _map(reference, matrix) - _map(reference, old[0]), axis=1
                    )
                )
                < tolerance
                for old in candidates
            ):
                continue
            candidates.append((matrix, ri, ci, rmse))
    if not candidates:
        raise ValueError("未找到满足几何门槛的圆心图案")
    if len(candidates) != 1:
        raise ValueError("圆心图案存在多个有效位姿，不能确定槽位对应关系")
    return (*candidates[0], hypotheses)


def handle_node(request):
    """输出参考到当前图像的标准变换和带明确参考点名称的匹配记录。"""
    control = build_node_execution_control(request)
    control.raise_if_cancelled_or_expired()
    try:
        settings = Settings.model_validate(request.parameters)
    except ValidationError as exc:
        raise InvalidRequestError("Circle Pattern Locate 参数无效") from exc
    points = sorted(settings.reference_points, key=lambda point: point.point_id)
    if len({point.point_id for point in points}) != len(points):
        raise InvalidRequestError("参考圆心 point_id 不能重复")
    circles = require_circles_payload(request.input_values.get("circles"))
    if (
        circles["unit"] != "pixel"
        or circles["coordinate_space"] != "source-image-pixels"
    ):
        raise InvalidRequestError("圆心配准要求 source-image-pixels 像素坐标")
    if len(circles["items"]) > 200:
        raise InvalidRequestError("圆心配准最多接受 200 个候选圆")
    observed = sorted(circles["items"], key=lambda item: tuple(item["center_xy"]))
    try:
        matrix, ri, ci, rmse, hypotheses = locate_pattern(
            [point.center_xy for point in points],
            [item["center_xy"] for item in observed],
            settings,
            check=control.raise_if_cancelled_or_expired,
        )
    except ValueError as exc:
        raise InvalidRequestError(
            str(exc), details={"error_code": "circle_pattern_localization_failed"}
        ) from exc
    matches = [
        {
            "point_id": points[int(r)].point_id,
            "reference_xy": list(points[int(r)].center_xy),
            "observed_xy": observed[int(c)]["center_xy"],
        }
        for r, c in zip(ri, ci)
    ]
    transform = build_planar_transform_payload(
        matrix_3x3=matrix.tolist(),
        inverse_matrix_3x3=np.linalg.inv(matrix).tolist(),
        source_coordinate_space="template-image-pixels",
        target_coordinate_space="source-image-pixels",
        match_count=len(points),
        inlier_count=len(matches),
        inlier_match_ids=[item["point_id"] for item in matches],
        reprojection_error=rmse,
        source_a_image=None,
        source_b_image=circles.get("source_image"),
        transform_kind="rigid",
    )
    return {
        "transform": transform,
        "summary": build_value_payload(
            {
                "state": "found",
                "reference_count": len(points),
                "candidate_count": len(observed),
                "matched_count": len(matches),
                "rmse_px": rmse,
                "hypothesis_count": hypotheses,
                "angle_degrees": math.degrees(math.atan2(matrix[1, 0], matrix[0, 0])),
                "translation_xy": matrix[:2, 2].tolist(),
                "matches": matches,
            }
        ),
    }
